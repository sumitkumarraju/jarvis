"""Laya System 1 decisions; parameterized/ambiguous tasks stay with System 2.

Laya is a classifier, not a speech recognizer or text generator. A high-confidence
choice must also agree with an explicit allowlisted command before tool execution.
No model-generated arguments, shell commands, or file mutations enter this path.
"""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1)
def installed_apps() -> tuple[str, ...]:
    names = set()
    for directory in (Path('/Applications'), Path('/System/Applications'), Path('/System/Applications/Utilities'), Path.home() / 'Applications'):
        try:
            names.update(app.stem for app in directory.glob('*.app'))
        except OSError:
            continue
    return tuple(sorted(names))


def native_app_action(text: str) -> dict | None:
    if not isinstance(text, str) or len(text) > 160:
        return None
    command = text.casefold().strip().rstrip('.,!?')
    command = re.sub(r'^(?:(?:hey\s+)?jarvis[,\s]+|wake up jarvis[,\s]+)', '', command)
    command = re.sub(r'^(?:(?:can|could|would|will) you\s+)?(?:please\s+)?', '', command)
    command = re.sub(r'\s+(?:for me|please)$', '', command)
    match = re.fullmatch(r'(?:open|launch|start)\s+(?:the\s+)?(.+?)(?:\s+app)?', command)
    if not match:
        return None
    requested = match.group(1).strip()
    aliases = {'chrome': 'Google Chrome', 'google chrome': 'Google Chrome', 'brave': 'Brave Browser', 'vs code': 'Visual Studio Code', 'vscode': 'Visual Studio Code'}
    requested = aliases.get(requested, requested).casefold()
    # Built-in names preserve established commands; additional targets come only
    # from application bundle names, never arbitrary paths or generated arguments.
    names = {'Safari', 'Notes', 'Spotify', 'Calculator', *installed_apps()}
    app = next((name for name in names if name.casefold() == requested), None)
    if app is None:
        return None
    return {'tool': 'open_app', 'args': {'app_name': app}, 'reply': f'Opened {app}.'}

ACTIONS = {
    'spotify_play': {'tool': 'spotify_playback', 'args': {'action': 'play'}, 'reply': 'Spotify playing.'},
    'spotify_pause': {'tool': 'spotify_playback', 'args': {'action': 'pause'}, 'reply': 'Spotify paused.'},
    'spotify_next': {'tool': 'spotify_playback', 'args': {'action': 'next'}, 'reply': 'Skipped to the next track.'},
    'spotify_previous': {'tool': 'spotify_playback', 'args': {'action': 'previous'}, 'reply': 'Playing the previous track.'},
    **{f'open_{app.lower()}': {'tool': 'open_app', 'args': {'app_name': app}, 'reply': f'Opened {app}.'}
       for app in ('Safari', 'Notes', 'Spotify', 'Calculator')},
}
CRITERIA = {
    'spotify_play': 'Explicitly resume or play Spotify playback, no particular song requested.',
    'spotify_pause': 'Explicitly pause or stop Spotify playback.',
    'spotify_next': 'Explicitly skip to the next Spotify track.',
    'spotify_previous': 'Explicitly play the previous Spotify track.',
    **{f'open_{app.lower()}': f'Explicitly open or launch the {app} application.'
       for app in ('Safari', 'Notes', 'Spotify', 'Calculator')},
    'process': 'Any question, negation, ambiguous instruction, compound task, or request requiring reasoning or parameters.',
}


def explicit_action(text: str) -> str | None:
    if not isinstance(text, str) or len(text) > 160:
        return None
    command = re.sub(r'[.,!?]', '', text.casefold()).strip()
    command = re.sub(r'^(?:hey\s+)?jarvis\s+', '', command)
    command = re.sub(r'^please\s+|\s+please$', '', command).strip()
    for app in ('safari', 'notes', 'spotify', 'calculator'):
        if command in (f'open {app}', f'launch {app}'):
            return f'open_{app}'
    phrases = {
        'spotify_play': ('play spotify', 'resume spotify', 'play music', 'resume music', 'spotify play'),
        'spotify_pause': ('pause spotify', 'stop spotify', 'pause music', 'stop music', 'spotify pause'),
        'spotify_next': ('next track', 'next song', 'skip track', 'skip song', 'spotify next', 'next spotify track'),
        'spotify_previous': ('previous track', 'previous song', 'spotify previous', 'previous spotify track'),
    }
    return next((action for action, candidates in phrases.items() if command in candidates), None)


class ReactiveRouter:
    def __init__(self, backend=None, on_status=None):
        self.backend = backend
        self.on_status = on_status or (lambda message: None)
        self._unavailable = False

    def decide(self, text: str) -> dict | None:
        native = native_app_action(text)
        if native is not None:
            self.on_status(f"Opening {native['args']['app_name']} directly…")
            return native
        expected = explicit_action(text)
        if expected is None or self._unavailable:
            return None
        try:
            if self.backend is None:
                self.on_status('Loading Laya decision model for reactive commands…')
                from laya import Router
                import torch
                # Keep CPU inference bounded so audio capture remains responsive.
                torch.set_num_threads(2)
                self.backend = Router(device='cpu', max_loaded=1)
            self.on_status('Laya is selecting a reactive action…')
            result = self.backend.predict(text, {
                'action': {'type': 'choice', 'instructions': 'Choose the single explicitly requested desktop action. Choose process if unsure. Never infer an action from a question or negation.', 'criteria': {expected: CRITERIA[expected], 'process': CRITERIA['process']}}
            })
            answer = result['answers']['action']
            choice = answer['choice']
            probability = float(answer.get('probabilities', {}).get(choice, 0))
            if choice == expected and probability >= .9:
                self.on_status('Laya reactive command')
                action = ACTIONS[choice]
                return {**action, 'args': dict(action['args'])}
            self.on_status('Laya deferred to the selected processing model.')
        except Exception:
            # Preserve regular model processing if the optional decision model cannot run.
            self._unavailable = True
            self.on_status('Laya unavailable; fallback to the selected processing model.')
        return None
