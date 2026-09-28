"""Bridge between Python (Jarvis + voice) and the webview frontend."""
from __future__ import annotations

import json
import threading
from typing import Any

from agent.jarvis import Jarvis
from voice.speak import speak, stop as stop_speech
from voice.listen import ContinuousListener


def _js_safe(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


class Bridge:
    """Methods on this class are callable from JS via window.pywebview.api.*"""

    def __init__(self):
        self.window = None
        self.jarvis = Jarvis()
        self.listener: ContinuousListener | None = None
        self.voice_on = False
        self._busy = threading.Lock()
        self._speak_lock = threading.Lock()

    # called from main.py once the window exists
    def attach(self, window) -> None:
        self.window = window

    def _emit(self, event: str, payload: Any = None) -> None:
        if not self.window:
            return
        try:
            self.window.evaluate_js(f"window.jarvisEvent({_js_safe(event)}, {_js_safe(payload)})")
        except Exception:
            pass

    # ===== exposed to JS =====
    def ready(self) -> dict:
        from config import JARVIS_PROVIDER, OLLAMA_MODEL, OPENAI_MODEL, SILENCE_TIMEOUT
        model = OPENAI_MODEL if JARVIS_PROVIDER in {"openai", "omniroute", "claude"} else OLLAMA_MODEL
        return {
            "model": model,
            "provider": JARVIS_PROVIDER,
            "voice": self.voice_on,
            "silence_timeout": SILENCE_TIMEOUT,
        }

    def send_message(self, text: str, voiced: bool = False) -> None:
        text = (text or "").strip()
        if not text:
            return
        threading.Thread(target=self._run_turn, args=(text, voiced), daemon=True).start()

    def toggle_voice(self) -> bool:
        self.voice_on = not self.voice_on
        if self.voice_on:
            self._start_listener()
        else:
            self._stop_listener()
            self._emit("mic_state", {"state": "idle", "level": 0.0})
        return self.voice_on

    def reset(self) -> None:
        self.jarvis.reset()
        self._emit("reset")

    def interrupt(self) -> None:
        stop_speech()
        self._emit("speech_stopped")

    # ===== listener wiring =====
    def _start_listener(self) -> None:
        if self.listener:
            return
        self.listener = ContinuousListener(on_state=self._on_mic_state)
        self.listener.start()
        threading.Thread(target=self._drain_listener, daemon=True).start()

    def _stop_listener(self) -> None:
        if self.listener:
            self.listener.stop()
            self.listener = None

    def _on_mic_state(self, state) -> None:
        if self._busy.locked():
            return
        self._emit("mic_state", {"state": "listen", "level": state.rms})

    def _drain_listener(self) -> None:
        while self.listener:
            try:
                text = self.listener.out.get(timeout=0.2)
            except Exception:
                continue
            text = (text or "").strip()
            if len(text) < 2:
                continue
            self._emit("user_voice", {"text": text})
            self.send_message(text, voiced=True)

    # ===== turn loop =====
    def _run_turn(self, text: str, voiced: bool) -> None:
        with self._busy:
            self._emit("turn_start", {"text": text, "voiced": voiced})
            self._emit("mic_state", {"state": "thinking", "level": 0.0})

            speak_buf = ""
            try:
                for chunk in self.jarvis.stream(text, on_tool=self._on_tool):
                    self._emit("chunk", {"text": chunk})
                    if voiced:
                        speak_buf += chunk
                        # speak after each sentence boundary
                        speak_buf = self._flush_sentences(speak_buf)
            except Exception as e:
                self._emit("error", {"message": str(e)})

            if voiced and speak_buf.strip():
                self._speak(speak_buf.strip())

            self._emit("turn_end")
            self._emit("mic_state", {"state": "listen" if self.voice_on else "idle", "level": 0.0})

    def _flush_sentences(self, buf: str) -> str:
        # speak everything up to the last sentence terminator
        last = max(buf.rfind("."), buf.rfind("!"), buf.rfind("?"))
        if last == -1:
            return buf
        ready = buf[: last + 1].strip()
        rest = buf[last + 1 :]
        if ready:
            self._speak(ready)
        return rest

    def _speak(self, text: str) -> None:
        with self._speak_lock:
            self._emit("mic_state", {"state": "speak", "level": 0.0})
            speak(text)
            self._emit("mic_state", {"state": "listen" if self.voice_on else "idle", "level": 0.0})

    def _on_tool(self, name: str, args: dict) -> None:
        self._emit("tool", {"name": name, "args": args})
