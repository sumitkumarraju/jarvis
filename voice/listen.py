"""Lazy, continuous microphone capture with VAD and local Whisper transcription."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING
from uuid import uuid4

if TYPE_CHECKING:
    from faster_whisper import WhisperModel
    import numpy as np

from config import (
    WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE, WHISPER_LANGUAGE,
    SAMPLE_RATE, SILENCE_TIMEOUT, SPEECH_THRESHOLD, CLAP_THRESHOLD, safe_error,
)
from voice.speak import is_speaking
from voice.wake import WakeGate

BLOCK = 1024
BLOCKS_PER_SEC = SAMPLE_RATE / BLOCK
SILENCE_BLOCKS = max(1, int(SILENCE_TIMEOUT * BLOCKS_PER_SEC))
MIN_SPEECH_BLOCKS = max(1, int(0.3 * BLOCKS_PER_SEC))
PARTIAL_MIN_BLOCKS = max(1, int(.6 * BLOCKS_PER_SEC))
PARTIAL_INTERVAL = .65
PARTIAL_WINDOW_BLOCKS = int(6 * BLOCKS_PER_SEC)

_model: WhisperModel | None = None
_model_lock = threading.Lock()
_inference_lock = threading.Lock()


def get_model() -> WhisperModel:
    global _model
    with _model_lock:
        if _model is None:
            from faster_whisper import WhisperModel
            _model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
        return _model


@dataclass
class MicState:
    rms: float = 0.0
    listening: bool = False
    phase: str = 'idle'


class ContinuousListener:
    """Start is nonblocking; every restart has its own cancellation event.

    ``discard_pending`` invalidates capture and in-flight transcription at turn
    boundaries. Capture is also suppressed while the assistant is busy/speaking.
    """

    def __init__(self, on_state=None, on_partial=None, on_error=None, is_suppressed=None, wake_mode='always'):
        self.wake = WakeGate(wake_mode, clap_threshold=CLAP_THRESHOLD)
        self.out: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lifecycle_lock = threading.Lock()
        self._epoch_lock = threading.Lock()
        self._epoch = 0
        self._active_utterance = None
        self.state = MicState()
        self.on_state = on_state
        self.on_partial = on_partial
        self.on_error = on_error
        self.is_suppressed = is_suppressed or (lambda: False)

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._thread and self._thread.is_alive() and not self._stop.is_set():
                return
            self.discard_pending()
            self._stop = threading.Event()
            self.state = MicState()
            self._thread = threading.Thread(target=self._run, args=(self._stop, self.state), daemon=True)
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop.set()
            thread = self._thread
        self.discard_pending()
        if thread and thread is not threading.current_thread():
            # Downloads/inference cannot be cancelled; never wait for them in the GUI.
            thread.join(timeout=0.25)

    def discard_pending(self) -> None:
        with self._epoch_lock:
            self._epoch += 1
            self._active_utterance = None
            while True:
                try:
                    self.out.get_nowait()
                except queue.Empty:
                    return

    def set_wake_mode(self, mode: str) -> None:
        self.wake.set_mode(mode)
        self.discard_pending()
        if self.state.listening:
            self.state.phase = 'listen' if self.wake.is_armed() else 'waiting_wake'
            self._publish_state(self.state, self._stop)

    def _suppressed(self) -> bool:
        return is_speaking() or self.is_suppressed()

    def _publish_state(self, state: MicState, stop: threading.Event) -> None:
        if self.on_state and self._stop is stop:
            try:
                self.on_state(state)
            except Exception:
                pass

    def _publish_transcript(self, payload: dict, epoch: int, utterance: str, stop: threading.Event) -> None:
        if not self.on_partial or stop.is_set() or self._stop is not stop or self._suppressed():
            return
        with self._epoch_lock:
            if epoch != self._epoch or (not payload['final'] and utterance != self._active_utterance):
                return
        try:
            self.on_partial(payload)
        except Exception:
            pass

    def _preview_loop(self, jobs: queue.Queue, stop: threading.Event) -> None:
        while not stop.is_set():
            try:
                epoch, utterance, audio = jobs.get(timeout=.2)
            except queue.Empty:
                continue
            with self._epoch_lock:
                if epoch != self._epoch or utterance != self._active_utterance:
                    continue
            if self._suppressed():
                continue
            try:
                text = self._transcribe(audio, partial=True)
            except Exception:
                # A preview failure must not disable final recognition or commands.
                return
            if text:
                self._publish_transcript({'id': utterance, 'text': text, 'final': False, 'accepted': False}, epoch, utterance, stop)

    def _run(self, stop: threading.Event, state: MicState) -> None:
        stage = "dependencies"
        state.phase = 'starting'
        self._publish_state(state, stop)
        try:
            import numpy as np
            import sounddevice as sd

            q: queue.Queue = queue.Queue(maxsize=32)
            recording = threading.Event()

            def cb(indata, frames, time_info, status):
                if stop.is_set() or not recording.is_set():
                    return
                if self._suppressed():
                    self.discard_pending()
                    return
                with self._epoch_lock:
                    epoch = self._epoch
                try:
                    q.put_nowait((epoch, time.monotonic(), indata.copy()))
                except queue.Full:
                    pass

            stage = "microphone"
            with sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1, dtype="float32",
                blocksize=BLOCK, callback=cb,
            ):
                if stop.is_set():
                    return
                stage = "model"
                state.phase = 'loading_model'
                self._publish_state(state, stop)
                get_model()
                if stop.is_set():
                    return
                stage = "transcription"
                preview_jobs: queue.Queue = queue.Queue(maxsize=1)
                if self.on_partial:
                    threading.Thread(target=self._preview_loop, args=(preview_jobs, stop), daemon=True).start()
                buf = []
                silence = 0
                speaking = False
                utterance = ''
                last_preview = 0.0
                with self._epoch_lock:
                    buffer_epoch = self._epoch
                state.listening = True
                state.phase = 'listen' if self.wake.is_armed() else 'waiting_wake'
                recording.set()
                self._publish_state(state, stop)

                while not stop.is_set():
                    try:
                        epoch, captured_at, block = q.get(timeout=0.1)
                    except queue.Empty:
                        continue
                    with self._epoch_lock:
                        current_epoch = self._epoch
                    if buffer_epoch != current_epoch or self._suppressed():
                        buf.clear()
                        silence = 0
                        speaking = False
                        buffer_epoch = current_epoch
                    if epoch != current_epoch or self._suppressed():
                        state.rms = 0.0
                        self._publish_state(state, stop)
                        continue
                    rms = float(np.sqrt(np.mean(block ** 2)))
                    state.rms = rms
                    if self.wake.observe_rms(rms, now=captured_at):
                        buf.clear()
                        silence = 0
                        speaking = False
                        state.phase = 'awake'
                        self._publish_state(state, stop)
                        continue
                    waiting = not self.wake.is_armed()
                    state.phase = ('waiting_wake' if waiting else 'awake' if self.wake.mode != 'always' else 'listen')
                    if not waiting and (rms > SPEECH_THRESHOLD or speaking):
                        state.phase = 'hearing'
                    self._publish_state(state, stop)
                    if waiting and self.wake.mode == 'clap':
                        buf.clear()
                        silence = 0
                        speaking = False
                        continue
                    if rms > SPEECH_THRESHOLD:
                        if not speaking:
                            utterance = uuid4().hex
                            last_preview = 0.0
                            with self._epoch_lock:
                                self._active_utterance = utterance
                        buf.append(block)
                        silence = 0
                        speaking = True
                        if self.on_partial and len(buf) >= PARTIAL_MIN_BLOCKS and captured_at - last_preview >= PARTIAL_INTERVAL:
                            snapshot = np.concatenate(buf[-PARTIAL_WINDOW_BLOCKS:]).flatten()
                            try:
                                preview_jobs.get_nowait()
                            except queue.Empty:
                                pass
                            try:
                                preview_jobs.put_nowait((epoch, utterance, snapshot))
                            except queue.Full:
                                pass
                            last_preview = captured_at
                    elif speaking:
                        buf.append(block)
                        silence += 1
                        if silence >= SILENCE_BLOCKS and len(buf) >= MIN_SPEECH_BLOCKS:
                            audio = np.concatenate(buf).flatten()
                            buf.clear()
                            silence = 0
                            speaking = False
                            state.phase = 'transcribing'
                            state.rms = 0.0
                            self._publish_state(state, stop)
                            text = self._transcribe(audio)
                            command = None
                            with self._epoch_lock:
                                valid = not stop.is_set() and epoch == self._epoch and not self._suppressed()
                                if valid:
                                    command = self.wake.accept_text(text)
                                    state.phase = ('listen' if self.wake.mode == 'always' else 'awake' if self.wake.is_armed() else 'waiting_wake')
                                    self._active_utterance = None
                            if valid:
                                reason = 'command' if command else 'no_speech' if not text else 'wake' if self.wake.is_armed() else 'waiting_wake'
                                self._publish_transcript({'id': utterance, 'text': text, 'final': True, 'accepted': bool(command), 'command': command or '', 'reason': reason}, epoch, utterance, stop)
                                with self._epoch_lock:
                                    if command and epoch == self._epoch and not stop.is_set() and not self._suppressed():
                                        self.out.put(command)
                            self._publish_state(state, stop)
        except Exception as error:
            if not stop.is_set() and self._stop is stop and self.on_error:
                actions = {
                    "dependencies": "Voice dependencies unavailable. Install the project's voice requirements, then enable the microphone again.",
                    "microphone": "Microphone unavailable. Allow microphone access in System Settings > Privacy & Security > Microphone and check the input device, then retry.",
                    "model": "Could not load Whisper. Check WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE and checkpoint download connectivity, then retry.",
                    "transcription": "Whisper transcription failed. Check voice model/device settings, then enable the microphone again.",
                }
                try:
                    self.on_error(actions[stage] + " " + safe_error(error))
                except Exception:
                    pass
        finally:
            stop.set()
            state.listening = False
            state.phase = 'idle'
            state.rms = 0.0
            self._publish_state(state, stop)

    def _transcribe(self, audio: np.ndarray, partial: bool = False) -> str:
        # Preview and final decode share one model; keep inference serialized while
        # audio capture and VAD continue on their own threads. Drafts never execute.
        with _inference_lock:
            segments, _ = get_model().transcribe(
                audio, language=WHISPER_LANGUAGE, vad_filter=not partial, beam_size=1
            )
            return " ".join(segment.text.strip() for segment in segments).strip()
