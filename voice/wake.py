"""Local wake phrases and two separated energy pulses; no actions on activation.

Clap activation is an energy heuristic, not a sound classifier. Two loud impulses
can also wake it. Wake mode gates command submission, not microphone capture.
"""
import re
import threading
import time

MODES = ('always', 'phrase', 'clap', 'phrase_or_clap')
_PHRASE = re.compile(r'^\s*(?:hey\s+jarvis|wake\s+up\s+jarvis|jarvis)\b[\s,!.:?-]*', re.IGNORECASE)


class WakeGate:
    def __init__(self, mode='always', timeout=12.0, clap_threshold=.08):
        self._lock = threading.RLock()
        self.timeout = timeout
        self.clap_threshold = clap_threshold
        self.set_mode(mode)

    def set_mode(self, mode):
        if mode not in MODES:
            raise ValueError('Choose always, phrase, clap, or phrase_or_clap.')
        with self._lock:
            self.mode = mode
            self._armed_until = 0
            self._first_clap = None
            self._high = False

    def is_armed(self, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            return self.mode == 'always' or now < self._armed_until

    def observe_rms(self, level, now=None):
        now = time.monotonic() if now is None else now
        with self._lock:
            if self.mode not in ('clap', 'phrase_or_clap') or self.is_armed(now):
                return False
            if level < self.clap_threshold / 2:
                self._high = False
                return False
            if level < self.clap_threshold or self._high:
                return False
            self._high = True
            if self._first_clap is not None and .12 <= now - self._first_clap <= .8:
                self._armed_until = now + self.timeout
                self._first_clap = None
                return True
            self._first_clap = now
            return False

    def accept_text(self, text, now=None):
        now = time.monotonic() if now is None else now
        text = text.strip()
        if not text:
            return None
        with self._lock:
            if self.mode == 'always':
                return text
            phrase = _PHRASE.match(text) if self.mode in ('phrase', 'phrase_or_clap') else None
            if phrase:
                self._armed_until = now + self.timeout
                text = text[phrase.end():].strip()
                if not text:
                    return None
            if not self.is_armed(now):
                return None
            self._armed_until = 0
            self._first_clap = None
            return text
