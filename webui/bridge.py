"""Thread-safe Python API for the desktop webview. Heavy dependencies are lazy."""
from __future__ import annotations

import json
import queue
import threading
from typing import Any, TYPE_CHECKING

import config
from webui.settings import discover_models, load_selection, save_selection
from webui.permissions import shell_confirmation

if TYPE_CHECKING:
    from voice.listen import ContinuousListener


def speak(text: str) -> None:
    from voice.speak import speak as say, stop
    try:
        say(text)
    except Exception:
        # A failed TTS process launch must not leave the microphone suppressed.
        stop()
        raise


def stop_speech() -> None:
    from voice.speak import stop
    stop()


def _js_safe(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


class Bridge:
    """Methods are callable via ``window.pywebview.api``; turns are never queued."""

    def __init__(self):
        self.window = None
        self.jarvis = None
        self.provider, self.model = load_selection()
        self.listener: ContinuousListener | None = None
        self.voice_on = False
        self.wake_mode = config.WAKE_MODE
        self.last_transcript = None
        self._busy = threading.Lock()
        self._state_lock = threading.RLock()
        self._speak_lock = threading.Lock()
        self._speech_cancel = threading.Event()
        self._listener_generation = 0
        self._closed = False

    def attach(self, window) -> None:
        self.window = window
        events = getattr(window, "events", None)
        if events is not None and getattr(events, "closed", None) is not None:
            events.closed += self.shutdown

    def _emit(self, event: str, payload: Any = None) -> None:
        if not self.window:
            return
        try:
            self.window.evaluate_js(f"window.jarvisEvent({_js_safe(event)}, {_js_safe(payload)})")
        except Exception:
            pass

    # ===== exposed to JS =====
    def ready(self) -> dict:
        with self._state_lock:
            return {
                "model": self.model,
                "provider": self.provider,
                "voice": self.voice_on,
                "wake_mode": self.wake_mode,
                "speech_transcript": self.last_transcript,
                "voice_phase": getattr(getattr(self.listener, 'state', None), 'phase', 'starting' if self.voice_on else 'idle'),
                "busy": self._busy.locked(),
                "silence_timeout": config.SILENCE_TIMEOUT,
                "providers": config.provider_info(),
            }

    def list_models(self, provider: str) -> dict:
        return discover_models(provider)

    def _new_agent(self, provider: str, model: str):
        from agent.jarvis import Jarvis
        tools = self.jarvis.tools if self.jarvis is not None else None
        agent = Jarvis(tools=tools, provider=provider, model=model)
        if hasattr(agent, 'reactive'):
            if self.jarvis is not None and hasattr(self.jarvis, 'reactive'):
                agent.reactive = self.jarvis.reactive
            agent.reactive.on_status = lambda message: self._emit('processing_route', {'message': message})
        return agent

    def select_model(self, provider: str, model: str) -> dict:
        with self._state_lock:
            result = {"ok": False, "error": None, "model": self.model, "provider": self.provider}
            if self._closed:
                result["error"] = "Jarvis has shut down."
                return result
            if not self._busy.acquire(blocking=False):
                result["error"] = "A turn is busy. Wait before changing models."
                return result
        try:
            provider, model = config.validate_selection(provider, model)
            candidate = self._new_agent(provider, model)
            if self.jarvis is not None:
                candidate.history = list(self.jarvis.history)
            with self._state_lock:
                if self._closed:
                    raise RuntimeError("Jarvis has shut down.")
                # Persist first: a failed save leaves both the live agent and preferences unchanged.
                save_selection(provider, model)
                self.jarvis = candidate
                self.provider, self.model = provider, model
                result.update(ok=True, model=model, provider=provider)
        except Exception as error:
            result["error"] = config.safe_error(error)
        finally:
            with self._state_lock:
                self._busy.release()
                if result["ok"]:
                    self._emit("model_changed", self.ready())
        return result

    def send_message(self, text: str, voiced: bool = False) -> dict:
        return self._submit(text, voiced)

    def _submit(self, text: str, voiced: bool, listener=None, generation=None) -> dict:
        if not isinstance(text, str) or not text.strip():
            return {"ok": False, "error": "Enter a message first."}
        with self._state_lock:
            if self._closed:
                return {"ok": False, "error": "Jarvis has shut down."}
            if listener is not None and not self._listener_current(listener, generation):
                return {"ok": False, "error": "Microphone session stopped."}
            if not self._busy.acquire(blocking=False):
                return {"ok": False, "error": "A turn is busy. Wait before sending another message."}
            self._speech_cancel.clear()
            try:
                if self.listener:
                    self.listener.discard_pending()
                if listener is not None:
                    self._emit("user_voice", {"text": text.strip()})
                threading.Thread(target=self._run_turn, args=(text.strip(), bool(voiced)), daemon=True).start()
            except Exception as error:
                self._busy.release()
                message = config.safe_error(error)
                self._emit("error", {"message": message})
                return {"ok": False, "error": message}
        return {"ok": True, "error": None}

    def set_wake_mode(self, mode: str) -> dict:
        from voice.wake import MODES
        with self._state_lock:
            if self._closed or self._busy.locked():
                return {'ok': False, 'error': 'Wait until Jarvis finishes before changing wake mode.', 'wake_mode': self.wake_mode}
            if mode not in MODES:
                return {'ok': False, 'error': 'Invalid wake mode.', 'wake_mode': self.wake_mode}
            if self.listener:
                self.listener.set_wake_mode(mode)
            self.wake_mode = mode
            self._emit('wake_mode_changed', {'wake_mode': mode})
            return {'ok': True, 'error': None, 'wake_mode': mode}

    def toggle_voice(self) -> bool:
        stopped = None
        with self._state_lock:
            if self._closed:
                return False
            if self.voice_on:
                stopped = self._detach_listener()
                self._emit("voice_changed", {"voice": False})
                self._emit("mic_state", {"state": "idle", "level": 0.0})
            else:
                self.voice_on = True
                self._emit("voice_changed", {"voice": True})
                self._emit('mic_state', {'state': 'starting', 'level': 0.0})
                try:
                    self._start_listener()
                except Exception as error:
                    self._on_voice_error(
                        "Could not enable microphone. Check voice dependencies and microphone permissions, then retry. "
                        + config.safe_error(error), self.listener, self._listener_generation,
                    )
        self._stop_detached(stopped)
        with self._state_lock:
            return self.voice_on

    def reset(self) -> dict:
        with self._state_lock:
            if self._closed:
                return {"ok": False, "error": "Jarvis has shut down."}
            if not self._busy.acquire(blocking=False):
                return {"ok": False, "error": "A turn is busy. Wait before resetting."}
            try:
                if self.jarvis is not None:
                    self.jarvis.reset()
                self._emit("reset")
                return {"ok": True, "error": None}
            except Exception as error:
                return {"ok": False, "error": config.safe_error(error)}
            finally:
                self._busy.release()

    def interrupt(self) -> None:
        self._speech_cancel.set()
        try:
            stop_speech()
        except Exception as error:
            self._emit("error", {"message": config.safe_error(error)})
        self._emit("speech_stopped")

    def shutdown(self, *_args) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._speech_cancel.set()
            stopped = self._detach_listener()
            self._emit("voice_changed", {"voice": False})
            self._emit("mic_state", {"state": "idle", "level": 0.0})
        self._stop_detached(stopped)
        try:
            stop_speech()
        except Exception:
            pass

    # ===== listener wiring =====
    def _listener_current(self, listener, generation) -> bool:
        return (not self._closed and self.voice_on and self.listener is listener
                and self._listener_generation == generation)

    def _start_listener(self) -> None:
        from voice.listen import ContinuousListener
        self._listener_generation += 1
        generation = self._listener_generation
        listener = ContinuousListener(
            on_state=lambda state: self._on_mic_state(state, listener, generation),
            on_error=lambda message: self._on_voice_error(message, listener, generation),
            is_suppressed=lambda: self._busy.locked() or self._closed,
            wake_mode=self.wake_mode,
            on_partial=lambda payload: self._on_transcript(payload, listener, generation),
        )
        self.listener = listener
        listener.start()
        threading.Thread(target=self._drain_listener, args=(listener, generation), daemon=True).start()

    def _detach_listener(self):
        stopped = self.listener
        self.listener = None
        self.voice_on = False
        self._listener_generation += 1
        return stopped

    def _stop_detached(self, listener) -> None:
        if listener is not None:
            try:
                listener.stop()
            except Exception as error:
                self._emit("error", {"message": "Could not close microphone: " + config.safe_error(error)})

    def _stop_listener(self) -> None:
        with self._state_lock:
            stopped = self._detach_listener()
        self._stop_detached(stopped)

    def _on_voice_error(self, message: str, listener, generation: int) -> None:
        with self._state_lock:
            if self._closed or generation != self._listener_generation or self.listener is not listener:
                return
            stopped = self._detach_listener()
            self._emit("error", {"message": config.safe_error(RuntimeError(message))})
            self._emit("voice_changed", {"voice": False})
            self._emit("mic_state", {"state": "idle", "level": 0.0})
        self._stop_detached(stopped)

    def _on_transcript(self, payload: dict, listener, generation: int) -> None:
        with self._state_lock:
            if not self._listener_current(listener, generation) or self._busy.locked():
                return
            self.last_transcript = dict(payload)
            self._emit('speech_transcript', self.last_transcript)

    def _on_mic_state(self, state, listener, generation: int) -> None:
        with self._state_lock:
            if not self._listener_current(listener, generation) or self._busy.locked():
                return
            phase = getattr(state, 'phase', 'listen' if state.listening else 'idle')
            self._emit("mic_state", {"state": phase, "level": state.rms})

    def _drain_listener(self, listener, generation: int) -> None:
        while True:
            with self._state_lock:
                if not self._listener_current(listener, generation):
                    return
            try:
                text = listener.out.get(timeout=0.2)
            except queue.Empty:
                continue
            if isinstance(text, str) and len(text.strip()) >= 2:
                self._submit(text, True, listener, generation)

    # ===== turn loop =====
    def _confirm_shell(self, command: str) -> bool:
        if self._closed or self.window is None:
            return False
        self._emit('processing_route', {'message': 'Waiting for your approval in the desktop dialog.'})
        approved = self.window.create_confirmation_dialog(
            'Allow Jarvis to run this command?',
            'Only allow commands you understand.\n\n' + command,
        )
        self._emit('processing_route', {'message': 'Command approved.' if approved else 'Command denied.'})
        return approved is True and not self._closed

    def _run_turn(self, text: str, voiced: bool) -> None:
        with shell_confirmation(self._confirm_shell):
            self._execute_turn(text, voiced)

    def _execute_turn(self, text: str, voiced: bool) -> None:
        try:
            self._emit("turn_start", {"text": text, "voiced": voiced})
            self._emit("mic_state", {"state": "thinking", "level": 0.0})
            if self.jarvis is None:
                self.jarvis = self._new_agent(self.provider, self.model)
            speak_buf = ""
            for chunk in self.jarvis.stream(text, on_tool=self._on_tool):
                if self._closed:
                    break
                self._emit("chunk", {"text": chunk})
                if voiced:
                    speak_buf = self._flush_sentences(speak_buf + chunk)
            if voiced and speak_buf.strip():
                self._speak(speak_buf.strip())
        except Exception as error:
            self._emit("error", {"message": config.safe_error(error)})
        finally:
            with self._state_lock:
                try:
                    if self.listener:
                        self.listener.discard_pending()
                finally:
                    self._busy.release()
                    self._emit("turn_end")
                    phase = getattr(getattr(self.listener, 'state', None), 'phase', 'listen') if self.voice_on else 'idle'
                    self._emit("mic_state", {"state": phase, "level": 0.0})

    def _flush_sentences(self, buf: str) -> str:
        last = max(buf.rfind("."), buf.rfind("!"), buf.rfind("?"))
        if last == -1:
            return buf
        ready, rest = buf[:last + 1].strip(), buf[last + 1:]
        if ready:
            self._speak(ready)
        return rest

    def _speak(self, text: str) -> None:
        with self._speak_lock:
            if self._speech_cancel.is_set() or self._closed:
                return
            self._emit("mic_state", {"state": "speak", "level": 0.0})
            try:
                speak(text)
            except Exception:
                if not self._speech_cancel.is_set():
                    raise
            finally:
                state = "thinking" if self._busy.locked() and not self._closed else "idle"
                self._emit("mic_state", {"state": state, "level": 0.0})

    def _on_tool(self, name: str, args: dict) -> None:
        self._emit("tool", {"name": name, "args": args})
