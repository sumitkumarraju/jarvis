"""Voice lifecycle tests use fake audio/Whisper, never a real microphone/download."""
import importlib
import math
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class LazyVoiceTests(unittest.TestCase):
    def test_import_and_constructor_do_not_import_or_load_voice_dependencies(self):
        code = '''
import importlib.abc
import sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"numpy", "sounddevice", "faster_whisper"}:
            raise AssertionError("Eager voice import: " + fullname)
sys.meta_path.insert(0, Block())
from voice.listen import ContinuousListener
listener = ContinuousListener()
assert listener._thread is None
listener.stop()
'''
        result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class AudioBlock:
    def __init__(self, amplitude):
        self.amplitude = amplitude

    def copy(self):
        return self

    def __pow__(self, power):
        return self.amplitude ** power


class Audio:
    def flatten(self):
        return self


class ListenerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("voice.listen")
        self.streams = []
        owner = self
        class Stream:
            def __init__(self, **kwargs):
                self.callback = kwargs["callback"]
                self.closed = False
                owner.streams.append(self)
            def __enter__(self):
                return self
            def __exit__(self, *args):
                self.closed = True
        self.Stream = Stream
        patch = mock.patch.dict(sys.modules, {
            "numpy": types.SimpleNamespace(sqrt=math.sqrt, mean=lambda value: value,
                                            concatenate=lambda blocks: Audio()),
            "sounddevice": types.SimpleNamespace(InputStream=Stream),
        })
        patch.start()
        self.addCleanup(patch.stop)

    def test_warmup_and_transcription_phases_are_reported_without_claiming_ready(self):
        loading, release, ready = threading.Event(), threading.Event(), threading.Event()
        phases = []
        model = types.SimpleNamespace(transcribe=mock.Mock(return_value=([types.SimpleNamespace(text='pause Spotify')], None)))
        def load():
            loading.set()
            release.wait(2)
            return model
        def on_state(state):
            phases.append(getattr(state, 'phase', None))
            if state.listening:
                ready.set()
        with mock.patch.object(self.module, 'get_model', side_effect=load), \
             mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1), \
             mock.patch.object(self.module, 'is_speaking', return_value=False):
            listener = self.module.ContinuousListener(on_state=on_state)
            listener.start()
            self.assertTrue(loading.wait(1))
            try:
                self.assertIn('loading_model', phases)
                self.assertFalse(listener.state.listening)
                release.set()
                self.assertTrue(ready.wait(1))
                callback = self.streams[0].callback
                callback(AudioBlock(.1), None, None, None)
                callback(AudioBlock(0), None, None, None)
                self.assertEqual(listener.out.get(timeout=1), 'pause Spotify')
                self.assertIn('hearing', phases)
                self.assertIn('transcribing', phases)
                self.assertEqual(listener.state.phase, 'listen')
            finally:
                release.set()
                listener.stop()

    def test_microphone_permission_failure_reports_action_and_does_not_load_whisper(self):
        failed = threading.Event()
        errors = []
        def on_error(message):
            errors.append(message)
            failed.set()
        with mock.patch.dict(sys.modules, {
            "sounddevice": types.SimpleNamespace(InputStream=mock.Mock(side_effect=PermissionError("denied")))
        }), mock.patch.object(self.module, "get_model") as model:
            listener = self.module.ContinuousListener(on_error=on_error)
            listener.start()
            self.assertTrue(failed.wait(1))
            listener.stop()
            model.assert_not_called()
        self.assertIn("Microphone", errors[0])
        self.assertIn("Privacy", errors[0])
        self.assertFalse(listener.state.listening)

    def test_model_load_failure_reports_action_and_closes_stream(self):
        failed = threading.Event()
        errors = []
        def on_error(message):
            errors.append(message)
            failed.set()
        with mock.patch.object(self.module, "get_model", side_effect=RuntimeError("missing checkpoint")):
            listener = self.module.ContinuousListener(on_error=on_error)
            listener.start()
            self.assertTrue(failed.wait(1))
            listener.stop()
        self.assertIn("Whisper", errors[0])
        self.assertIn("WHISPER_MODEL", errors[0])
        self.assertTrue(self.streams[0].closed)
        self.assertFalse(listener.state.listening)

    def test_stop_during_model_initialization_returns_promptly_and_prevents_late_delivery(self):
        loading, release = threading.Event(), threading.Event()
        errors = []
        def load():
            loading.set()
            release.wait(2)
            return object()
        with mock.patch.object(self.module, "get_model", side_effect=load):
            listener = self.module.ContinuousListener(on_error=errors.append)
            listener.start()
            self.assertTrue(loading.wait(1))
            try:
                start = time.monotonic()
                listener.stop()
                self.assertLess(time.monotonic() - start, 0.6)
            finally:
                release.set()
                listener._thread.join(1)
        self.assertTrue(self.streams[0].closed)
        self.assertTrue(listener.out.empty())
        self.assertEqual(errors, [])
        self.assertFalse(listener.state.listening)

    def test_audio_utterance_is_transcribed_with_configured_language_and_vad(self):
        ready = threading.Event()
        model = types.SimpleNamespace(transcribe=mock.Mock(return_value=([types.SimpleNamespace(text=" hello ")], None)))
        with mock.patch.object(self.module, "get_model", return_value=model), \
             mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1, WHISPER_LANGUAGE="en"), \
             mock.patch.object(self.module, "is_speaking", return_value=False):
            listener = self.module.ContinuousListener(on_state=lambda state: ready.set() if state.listening else None)
            listener.start()
            self.assertTrue(ready.wait(1))
            try:
                callback = self.streams[0].callback
                callback(AudioBlock(0.1), None, None, None)
                callback(AudioBlock(0.0), None, None, None)
                self.assertEqual(listener.out.get(timeout=1), "hello")
                self.assertEqual(model.transcribe.call_args.kwargs,
                                 {"language": "en", "vad_filter": True, "beam_size": 1})
            finally:
                listener.stop()

    def test_final_transcript_is_visible_even_when_wake_gate_rejects_command(self):
        ready, displayed = threading.Event(), threading.Event()
        transcripts = []
        model = types.SimpleNamespace(transcribe=mock.Mock(return_value=([types.SimpleNamespace(text='open Chrome')], None)))
        def on_partial(payload):
            transcripts.append(payload)
            if payload.get('final'):
                displayed.set()
        with mock.patch.object(self.module, 'get_model', return_value=model), \
             mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1), \
             mock.patch.object(self.module, 'is_speaking', return_value=False):
            listener = self.module.ContinuousListener(on_state=lambda state: ready.set() if state.listening else None, on_partial=on_partial, wake_mode='phrase')
            listener.start()
            self.assertTrue(ready.wait(1))
            try:
                callback = self.streams[0].callback
                callback(AudioBlock(.03), None, None, None)
                callback(AudioBlock(0), None, None, None)
                self.assertTrue(displayed.wait(1), 'recognized but ignored words were not shown')
                final = next(payload for payload in transcripts if payload['final'])
                self.assertEqual(final['text'], 'open Chrome')
                self.assertFalse(final['accepted'])
                self.assertEqual(final['reason'], 'waiting_wake')
                self.assertTrue(listener.out.empty())
            finally:
                listener.stop()

    def test_live_draft_transcription_does_not_execute_or_block_microphone_capture(self):
        ready, inference_started, release, displayed, captured = [threading.Event() for _ in range(5)]
        transcripts = []
        states = []
        def transcribe(audio, partial=False):
            if partial:
                inference_started.set()
                release.wait(2)
            return 'open Chrome'
        def on_state(state):
            if state.listening:
                ready.set()
            states.append(state.rms)
            if len(states) >= 15:
                captured.set()
        def on_partial(payload):
            transcripts.append(payload)
            displayed.set()
        with mock.patch.object(self.module, 'get_model', return_value=object()), \
             mock.patch.object(self.module.ContinuousListener, '_transcribe', side_effect=transcribe), \
             mock.patch.multiple(self.module, PARTIAL_MIN_BLOCKS=1, PARTIAL_INTERVAL=0), \
             mock.patch.object(self.module, 'is_speaking', return_value=False):
            listener = self.module.ContinuousListener(on_state=on_state, on_partial=on_partial)
            listener.start()
            self.assertTrue(ready.wait(1))
            try:
                callback = self.streams[0].callback
                for _ in range(20):
                    callback(AudioBlock(.03), None, None, None)
                self.assertTrue(inference_started.wait(1))
                self.assertTrue(captured.wait(1), 'draft decoding blocked input level updates')
                self.assertTrue(listener.out.empty(), 'a draft must never execute a command')
                release.set()
                self.assertTrue(displayed.wait(1))
                self.assertFalse(transcripts[0]['final'])
                self.assertEqual(transcripts[0]['text'], 'open Chrome')
            finally:
                release.set()
                listener.stop()

    def test_stopped_microphone_cannot_publish_a_late_draft(self):
        ready, started, release = threading.Event(), threading.Event(), threading.Event()
        transcripts = []
        def transcribe(audio, partial=False):
            started.set()
            release.wait(2)
            return 'late transcript'
        with mock.patch.object(self.module, 'get_model', return_value=object()), \
             mock.patch.object(self.module.ContinuousListener, '_transcribe', side_effect=transcribe), \
             mock.patch.multiple(self.module, PARTIAL_MIN_BLOCKS=1, PARTIAL_INTERVAL=0), \
             mock.patch.object(self.module, 'is_speaking', return_value=False):
            listener = self.module.ContinuousListener(on_state=lambda state: ready.set() if state.listening else None, on_partial=transcripts.append)
            listener.start()
            self.assertTrue(ready.wait(1))
            self.streams[0].callback(AudioBlock(.03), None, None, None)
            self.assertTrue(started.wait(1))
            listener.stop()
            release.set()
            time.sleep(.1)
            self.assertEqual(transcripts, [])
            self.assertTrue(listener.out.empty())

    def test_wake_phrase_gates_transcription_before_submitting_a_command(self):
        ready = threading.Event()
        phases = []
        replies = iter(['background conversation', 'Hey Jarvis, open Safari'])
        model = types.SimpleNamespace(transcribe=lambda *args, **kwargs: ([types.SimpleNamespace(text=next(replies))], None))
        def on_state(state):
            phases.append(state.phase)
            if state.listening:
                ready.set()
        with mock.patch.object(self.module, 'get_model', return_value=model), \
             mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1), \
             mock.patch.object(self.module, 'is_speaking', return_value=False):
            listener = self.module.ContinuousListener(on_state=on_state, wake_mode='phrase')
            listener.start()
            self.assertTrue(ready.wait(1))
            try:
                callback = self.streams[0].callback
                for _ in range(2):
                    callback(AudioBlock(.1), None, None, None)
                    callback(AudioBlock(0), None, None, None)
                self.assertEqual(listener.out.get(timeout=1), 'open Safari')
                self.assertTrue(listener.out.empty())
                self.assertIn('waiting_wake', phases)
            finally:
                listener.stop()

    def test_double_clap_activates_listener_and_submits_only_the_following_command(self):
        ready = threading.Event()
        phases = []
        model = types.SimpleNamespace(transcribe=mock.Mock(return_value=([types.SimpleNamespace(text='open Safari')], None)))
        start = time.monotonic()
        capture_clock = types.SimpleNamespace(monotonic=mock.Mock(side_effect=[start, start+.06, start+.3, start+.36, start+.5, start+.6]))
        def on_state(state):
            phases.append(state.phase)
            if state.listening:
                ready.set()
        with mock.patch.object(self.module, 'get_model', return_value=model), \
             mock.patch.object(self.module, 'time', capture_clock), \
             mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1), \
             mock.patch.object(self.module, 'is_speaking', return_value=False):
            listener = self.module.ContinuousListener(on_state=on_state, wake_mode='clap')
            listener.start()
            self.assertTrue(ready.wait(1))
            try:
                callback = self.streams[0].callback
                for amplitude in [.2, 0, .2, 0, .03, 0]:
                    callback(AudioBlock(amplitude), None, None, None)
                self.assertEqual(listener.out.get(timeout=1), 'open Safari')
                self.assertIn('awake', phases)
                self.assertEqual(model.transcribe.call_count, 1)
                self.assertTrue(listener.out.empty())
            finally:
                listener.stop()

    def test_clap_only_mode_does_not_transcribe_while_waiting_for_wake(self):
        ready = threading.Event()
        model = types.SimpleNamespace(transcribe=mock.Mock(return_value=([], None)))
        with mock.patch.object(self.module, 'get_model', return_value=model), \
             mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1), \
             mock.patch.object(self.module, 'is_speaking', return_value=False):
            listener = self.module.ContinuousListener(on_state=lambda state: ready.set() if state.listening else None, wake_mode='clap')
            listener.start()
            self.assertTrue(ready.wait(1))
            try:
                callback = self.streams[0].callback
                callback(AudioBlock(.03), None, None, None)
                callback(AudioBlock(0), None, None, None)
                time.sleep(.15)
                model.transcribe.assert_not_called()
                self.assertTrue(listener.out.empty())
            finally:
                listener.stop()

    def test_audio_captured_during_speech_or_a_turn_cannot_form_an_utterance(self):
        for suppress_source in ("turn", "speech"):
            with self.subTest(source=suppress_source):
                ready, suppressed = threading.Event(), threading.Event()
                model = types.SimpleNamespace(transcribe=mock.Mock(return_value=([types.SimpleNamespace(text="fresh")], None)))
                with mock.patch.object(self.module, "get_model", return_value=model), \
                     mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1), \
                     mock.patch.object(self.module, "is_speaking", side_effect=lambda: suppress_source == "speech" and suppressed.is_set()):
                    listener = self.module.ContinuousListener(
                        on_state=lambda state: ready.set() if state.listening else None,
                        is_suppressed=lambda: suppress_source == "turn" and suppressed.is_set(),
                    )
                    listener.start()
                    self.assertTrue(ready.wait(1))
                    try:
                        callback = self.streams[-1].callback
                        suppressed.set()
                        callback(AudioBlock(0.1), None, None, None)
                        callback(AudioBlock(0.0), None, None, None)
                        suppressed.clear()
                        callback(AudioBlock(0.1), None, None, None)
                        callback(AudioBlock(0.0), None, None, None)
                        self.assertEqual(listener.out.get(timeout=1), "fresh")
                        self.assertEqual(model.transcribe.call_count, 1)
                        self.assertTrue(listener.out.empty())
                    finally:
                        listener.stop()

    def test_transcription_finishing_after_a_turn_discards_pre_turn_audio(self):
        ready, entered, release, returned, after = (threading.Event() for _ in range(5))
        def transcribe(*args, **kwargs):
            entered.set()
            release.wait(2)
            returned.set()
            return [types.SimpleNamespace(text="stale transcript")], None
        def on_state(state):
            if state.listening:
                ready.set()
            if returned.is_set() and state.rms > 0:
                after.set()
        model = types.SimpleNamespace(transcribe=transcribe)
        with mock.patch.object(self.module, "get_model", return_value=model), \
             mock.patch.multiple(self.module, SILENCE_BLOCKS=1, MIN_SPEECH_BLOCKS=1), \
             mock.patch.object(self.module, "is_speaking", return_value=False):
            listener = self.module.ContinuousListener(on_state=on_state)
            listener.start()
            self.assertTrue(ready.wait(1))
            try:
                callback = self.streams[-1].callback
                callback(AudioBlock(0.1), None, None, None)
                callback(AudioBlock(0.0), None, None, None)
                self.assertTrue(entered.wait(1))
                listener.discard_pending()  # the bridge calls this at both turn boundaries
                release.set()
                self.assertTrue(returned.wait(1))
                callback(AudioBlock(0.1), None, None, None)
                self.assertTrue(after.wait(1))
                self.assertTrue(listener.out.empty())
            finally:
                release.set()
                listener.stop()

    def test_restart_uses_independent_stop_state_and_ignores_old_failure(self):
        loading, release, current_ready = threading.Event(), threading.Event(), threading.Event()
        errors = []
        calls = []
        def load():
            calls.append(True)
            if len(calls) == 1:
                loading.set()
                release.wait(2)
                raise RuntimeError("old load failed")
            return object()
        with mock.patch.object(self.module, "get_model", side_effect=load):
            listener = self.module.ContinuousListener(on_error=errors.append,
                on_state=lambda state: current_ready.set() if state.listening else None)
            listener.start()
            self.assertTrue(loading.wait(1))
            old_thread = listener._thread
            listener.stop()
            try:
                listener.start()
                self.assertTrue(current_ready.wait(1), "replacement listener did not start")
                release.set()
                old_thread.join(1)
                self.assertEqual(errors, [])
                self.assertTrue(listener.state.listening)
                self.assertFalse(listener._stop.is_set())
            finally:
                release.set()
                listener.stop()
                old_thread.join(1)


if __name__ == "__main__":
    unittest.main()
