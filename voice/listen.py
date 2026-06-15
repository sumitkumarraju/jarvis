"""Continuous microphone listener with simple VAD.

Streams audio and yields utterances when the user pauses. Suppresses input
while TTS is speaking to prevent the assistant from hearing itself.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
from faster_whisper import WhisperModel

from config import (
    WHISPER_MODEL, WHISPER_DEVICE, WHISPER_COMPUTE,
    SAMPLE_RATE, SILENCE_TIMEOUT, SPEECH_THRESHOLD,
)
from voice.speak import is_speaking

BLOCK = 1024
BLOCKS_PER_SEC = SAMPLE_RATE // BLOCK
SILENCE_BLOCKS = max(1, int(SILENCE_TIMEOUT * BLOCKS_PER_SEC))
MIN_SPEECH_BLOCKS = int(0.3 * BLOCKS_PER_SEC)

_model: WhisperModel | None = None


def get_model() -> WhisperModel:
    global _model
    if _model is None:
        _model = WhisperModel(WHISPER_MODEL, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)
    return _model


@dataclass
class MicState:
    rms: float = 0.0
    listening: bool = False


class ContinuousListener:
    """Background thread: produces transcribed utterances on `out_queue`.

    - Drops audio while is_speaking() is true (avoid self-echo).
    - Buffers blocks once volume crosses SPEECH_THRESHOLD; emits when SILENCE_TIMEOUT of quiet follows.
    """

    def __init__(self, on_state=None, on_partial=None):
        self.out: queue.Queue[str] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.state = MicState()
        self.on_state = on_state
        self.on_partial = on_partial

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _publish_state(self) -> None:
        if self.on_state:
            try: self.on_state(self.state)
            except Exception: pass

    def _run(self) -> None:
        get_model()  # warm
        q: queue.Queue = queue.Queue()

        def cb(indata, frames, time_info, status):
            q.put(indata.copy())

        with sd.InputStream(
            samplerate=SAMPLE_RATE, channels=1, dtype="float32",
            blocksize=BLOCK, callback=cb,
        ):
            buf: list[np.ndarray] = []
            silence = 0
            speaking = False
            self.state.listening = True
            self._publish_state()

            while not self._stop.is_set():
                try:
                    block = q.get(timeout=0.1)
                except queue.Empty:
                    continue

                if is_speaking():
                    # ignore audio while TTS is playing; reset partial buffer
                    buf.clear(); silence = 0; speaking = False
                    self.state.rms = 0.0
                    self._publish_state()
                    continue

                rms = float(np.sqrt(np.mean(block**2)))
                self.state.rms = rms
                self._publish_state()

                if rms > SPEECH_THRESHOLD:
                    buf.append(block)
                    silence = 0
                    speaking = True
                elif speaking:
                    buf.append(block)
                    silence += 1
                    if silence >= SILENCE_BLOCKS and len(buf) >= MIN_SPEECH_BLOCKS:
                        audio = np.concatenate(buf).flatten()
                        buf.clear(); silence = 0; speaking = False
                        text = self._transcribe(audio)
                        if text:
                            self.out.put(text)

    def _transcribe(self, audio: np.ndarray) -> str:
        try:
            segments, _ = get_model().transcribe(audio, language="en", vad_filter=True, beam_size=1)
            return " ".join(s.text.strip() for s in segments).strip()
        except Exception:
            return ""
