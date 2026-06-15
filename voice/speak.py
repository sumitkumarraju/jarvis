import subprocess
import threading
import time

from config import TTS_VOICE, TTS_RATE

_proc: subprocess.Popen | None = None
_lock = threading.Lock()
_speaking = threading.Event()


def is_speaking() -> bool:
    return _speaking.is_set()


def stop() -> None:
    global _proc
    with _lock:
        if _proc and _proc.poll() is None:
            _proc.terminate()
            try: _proc.wait(timeout=0.5)
            except Exception: _proc.kill()
        _proc = None
        _speaking.clear()


def speak(text: str, blocking: bool = True) -> None:
    """Speak text via macOS `say`. Cancels any in-flight speech first."""
    global _proc
    text = (text or "").strip()
    if not text:
        return
    stop()
    with _lock:
        _speaking.set()
        _proc = subprocess.Popen(
            ["say", "-v", TTS_VOICE, "-r", str(TTS_RATE), text],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    if blocking:
        try:
            _proc.wait()
        finally:
            _speaking.clear()
        # small tail so the mic doesn't catch the last syllable
        time.sleep(0.15)
