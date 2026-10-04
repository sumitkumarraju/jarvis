"""Backend contract tests; no desktop, model server, or ML runtime needed."""
import importlib
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import types
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


class StartupTests(unittest.TestCase):
    def test_bridge_boots_without_key_or_optional_dependencies(self):
        code = '''
import importlib.abc
import sys
class NoOptionalDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {
            "langchain_core", "langchain_ollama", "langchain_openai", "tools",
            "numpy", "sounddevice", "faster_whisper"
        }:
            raise AssertionError("Eager optional import: " + fullname)
sys.meta_path.insert(0, NoOptionalDependencies())
from webui.bridge import Bridge
bridge = Bridge()
assert bridge.jarvis is None
state = bridge.ready()
assert state["provider"] == "openai"
assert state["busy"] is False
assert state["voice"] is False
assert state["model"]
assert state["silence_timeout"] == 2.0
assert len(state["providers"]) == 4
assert all("key" not in provider for provider in state["providers"])
assert not next(p for p in state["providers"] if p["id"] == "openai")["key_configured"]
'''
        with tempfile.TemporaryDirectory() as home:
            env = dict(os.environ, HOME=home, JARVIS_PROVIDER="openai", OPENAI_API_KEY="",
                       JARVIS_SILENCE_TIMEOUT="2.0")
            result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env,
                                    text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


class Message:
    def __init__(self, content="", **kwargs):
        self.content = content
        self.tool_calls = kwargs.pop("tool_calls", [])
        self.additional_kwargs = kwargs.pop("additional_kwargs", {})
        self.__dict__.update(kwargs)


class FakeLLM:
    calls = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls.append(kwargs)

    def bind_tools(self, tools):
        self.tools = tools
        return self


class AgentTests(unittest.TestCase):
    def setUp(self):
        import config
        self.config_patch = mock.patch.multiple(config, JARVIS_PROVIDER="ollama",
                                               OLLAMA_MODEL="default-local", OPENAI_MODEL="default-api",
                                               OPENAI_API_KEY="test-secret")
        self.config_patch.start()
        messages = types.ModuleType("langchain_core.messages")
        for name in ("SystemMessage", "HumanMessage", "AIMessage", "ToolMessage", "AIMessageChunk"):
            setattr(messages, name, Message)
        self.default_tools = [types.SimpleNamespace(name="native_tool")]
        self.modules_patch = mock.patch.dict(sys.modules, {
            "langchain_core": types.ModuleType("langchain_core"),
            "langchain_core.messages": messages,
            "langchain_core.tools": types.SimpleNamespace(BaseTool=object),
            "langchain_ollama": types.SimpleNamespace(ChatOllama=FakeLLM),
            "langchain_openai": types.SimpleNamespace(ChatOpenAI=FakeLLM),
            "tools": types.SimpleNamespace(ALL_TOOLS=self.default_tools),
        })
        self.modules_patch.start()
        sys.modules.pop("agent.jarvis", None)
        self.agent = importlib.import_module("agent.jarvis")
        FakeLLM.calls = []

    def tearDown(self):
        sys.modules.pop("agent.jarvis", None)
        self.modules_patch.stop()
        self.config_patch.stop()

    def test_selected_provider_and_model_reach_the_llm(self):
        for provider in ("ollama", "openai", "omniroute", "claude"):
            with self.subTest(provider=provider):
                agent = self.agent.Jarvis(provider=provider, model="selected-model")
                self.assertEqual(agent.llm.kwargs["model"], "selected-model")
                self.assertEqual(agent.llm.kwargs["base_url"],
                                 self.agent.OLLAMA_HOST if provider == "ollama" else self.agent.OPENAI_BASE_URL)
                self.assertEqual(agent.tools, self.default_tools)
                self.assertEqual(agent.provider, provider)
                self.assertEqual(agent.model, "selected-model")
                self.assertEqual(len(agent.history), 1)
        default = self.agent.Jarvis()
        self.assertEqual(default.llm.kwargs["model"], "default-local")

    def test_unknown_provider_and_missing_compatible_key_fail_before_client_creation(self):
        for provider, model in (("unknown", "model"), ("ollama", ""), ("ollama", "\n")):
            with self.subTest(provider=provider, model=model), self.assertRaises(ValueError):
                self.agent.Jarvis(tools=[], provider=provider, model=model)
        with mock.patch.object(self.agent, "OPENAI_API_KEY", ""):
            with self.assertRaisesRegex(RuntimeError, "OPENAI_API_KEY"):
                self.agent.Jarvis(tools=[], provider="openai", model="model")
        self.assertEqual(FakeLLM.calls, [])

    def test_reactive_command_runs_native_tool_without_generative_request(self):
        from agent.reactive import ReactiveRouter
        backend = mock.Mock()
        backend.predict.return_value = {'answers': {'action': {'choice': 'spotify_pause', 'probabilities': {'spotify_pause': .99}}}}
        tool = types.SimpleNamespace(name='spotify_playback', invoke=mock.Mock(return_value='OK'))
        agent = self.agent.Jarvis(tools=[tool])
        agent.reactive = ReactiveRouter(backend=backend)
        agent.llm.stream = mock.Mock(side_effect=AssertionError('System 2 should not run'))
        on_tool = mock.Mock()
        self.assertEqual(list(agent.stream('pause Spotify', on_tool=on_tool)), ['Spotify paused.'])
        tool.invoke.assert_called_once_with({'action': 'pause'})
        on_tool.assert_called_once_with('spotify_playback', {'action': 'pause'})
        self.assertEqual(agent.history[-1].content, 'Spotify paused.')
        self.assertEqual(agent.history[-2].content, 'OK')

    def test_stream_and_chat_keep_native_tool_dispatch_and_history(self):
        tool = types.SimpleNamespace(name="desktop", invoke=mock.Mock(return_value="native result"))
        agent = self.agent.Jarvis(tools=[tool], provider="ollama", model="chosen")
        call = {"name": "desktop", "args": {"action": "play"}, "id": "tool-1"}
        chunks = iter([[Message(tool_calls=[call])], [Message(content="Done.")]])
        agent.llm.stream = lambda history: iter(next(chunks))
        on_tool = mock.Mock()
        self.assertEqual(list(agent.stream("play music", on_tool=on_tool)), ["Done."])
        on_tool.assert_called_once_with("desktop", {"action": "play"})
        tool.invoke.assert_called_once_with({"action": "play"})
        self.assertEqual(agent.history[-2].content, "native result")
        self.assertEqual(agent.history[-2].tool_call_id, "tool-1")
        agent.llm.invoke = lambda history: Message(content="Text reply")
        self.assertEqual(agent.chat("question"), "Text reply")
        agent.reset()
        self.assertEqual(len(agent.history), 1)


class FakeAgent:
    def __init__(self, tools=None, *, provider="ollama", model="default"):
        if model == "broken":
            raise RuntimeError("Cannot bind this model")
        self.provider = provider
        self.model = model
        self.tools = tools if tools is not None else ["desktop", "confirmed-shell"]
        self.history = ["system"]

    def reset(self):
        self.history = ["system"]

    def stream(self, text, on_tool=None):
        self.history.append(text)
        yield "Reply."


class ObservedQueue(queue.Queue):
    def __init__(self):
        super().__init__()
        self.get_calls = queue.Queue()

    def get(self, block=True, timeout=None):
        if block:
            self.get_calls.put(True)
        return super().get(block, timeout)


class FakeListener:
    def __init__(self, on_state=None, on_error=None, is_suppressed=None, wake_mode='always', on_partial=None):
        self.on_partial = on_partial
        self.wake_mode = wake_mode
        self.out = ObservedQueue()
        self.on_state = on_state
        self.on_error = on_error
        self.is_suppressed = is_suppressed
        self.stopped = False

    def start(self):
        pass

    def stop(self):
        self.stopped = True

    def set_wake_mode(self, mode):
        self.wake_mode = mode

    def discard_pending(self):
        while True:
            try:
                self.out.get_nowait()
            except queue.Empty:
                return


class BridgeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = mock.patch.dict(os.environ, {"HOME": self.temp.name}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        import config
        config_patch = mock.patch.multiple(config, JARVIS_PROVIDER="ollama", OLLAMA_MODEL="default-local")
        config_patch.start()
        self.addCleanup(config_patch.stop)
        modules = mock.patch.dict(sys.modules, {"agent.jarvis": types.SimpleNamespace(Jarvis=FakeAgent)})
        modules.start()
        self.addCleanup(modules.stop)
        self.module = importlib.import_module("webui.bridge")
        self.real_speak = self.module.speak
        speech = mock.patch.object(self.module, "speak")
        speech.start()
        self.addCleanup(speech.stop)
        self.bridge = self.module.Bridge()
        self.events = []
        self.bridge._emit = lambda event, payload=None: self.events.append((event, payload))
        self.addCleanup(self.bridge._stop_listener)

    def test_switch_preserves_history_tools_and_survives_restart(self):
        old = FakeAgent()
        old.history.extend(["user", "assistant"])
        self.bridge.jarvis = old
        result = self.bridge.select_model("omniroute", "runtime-api")
        self.assertEqual(result, {"ok": True, "error": None, "model": "runtime-api", "provider": "omniroute"})
        self.assertEqual(self.bridge.jarvis.history, old.history)
        self.assertIs(self.bridge.jarvis.tools, old.tools)
        self.assertEqual(self.bridge.jarvis.model, "runtime-api")
        self.assertEqual(self.bridge.jarvis.provider, "omniroute")
        self.assertEqual(self.events, [("model_changed", self.bridge.ready())])
        restarted = self.module.Bridge()
        self.assertEqual((restarted.provider, restarted.model), ("omniroute", "runtime-api"))
        self.assertIsNone(restarted.jarvis)
        saved = json.loads((Path(self.temp.name) / ".jarvis" / "ui-settings.json").read_text())
        self.assertEqual(saved, {"provider": "omniroute", "model": "runtime-api"})

    def test_busy_turn_rejects_duplicate_send_switch_and_reset(self):
        entered, release = threading.Event(), threading.Event()
        agent = FakeAgent()
        def stream(text, on_tool=None):
            agent.history.append(text)
            entered.set()
            release.wait(2)
            yield "complete"
        agent.stream = stream
        self.bridge.jarvis = agent
        try:
            self.assertEqual(self.bridge.send_message(" first "), {"ok": True, "error": None})
            self.assertTrue(entered.wait(1))
            self.assertTrue(self.bridge.ready()["busy"])
            self.assertFalse(self.bridge.send_message("duplicate")["ok"])
            self.assertFalse(self.bridge.select_model("ollama", "second")["ok"])
            self.assertFalse(self.bridge.reset()["ok"])
            self.assertEqual(agent.history, ["system", "first"])
        finally:
            release.set()
            if self.bridge._busy.acquire(timeout=2):
                self.bridge._busy.release()
        self.assertFalse(self.bridge.ready()["busy"])
        self.assertEqual([event for event, _ in self.events].count("turn_start"), 1)
        self.assertEqual([event for event, _ in self.events].count("turn_end"), 1)
        self.assertEqual(self.bridge.reset(), {"ok": True, "error": None})
        self.assertEqual(self.events[-1][0], "reset")

    def test_send_uses_lazy_selected_agent_and_rejects_empty_input(self):
        self.bridge.select_model("claude", "chosen-api")
        self.bridge.jarvis = None
        result = self.bridge.send_message("question")
        self.assertEqual(result, {"ok": True, "error": None})
        self.assertTrue(self.bridge._busy.acquire(timeout=2))
        self.bridge._busy.release()
        self.assertEqual(self.bridge.jarvis.model, "chosen-api")
        self.assertEqual(self.bridge.jarvis.provider, "claude")
        self.assertFalse(self.bridge.send_message("   ")["ok"])

    def test_tail_speech_failure_always_ends_the_turn(self):
        agent = FakeAgent()
        agent.stream = lambda *args, **kwargs: iter(["unfinished sentence"])
        self.bridge.jarvis = agent
        ended = threading.Event()
        def emit(event, payload=None):
            self.events.append((event, payload))
            if event == "turn_end":
                ended.set()
        self.bridge._emit = emit
        with mock.patch.object(self.module, "speak", side_effect=RuntimeError("say unavailable")):
            self.bridge.send_message("question", voiced=True)
            self.assertTrue(ended.wait(1), "turn_end missing after speech failure")
            self.assertTrue(self.bridge._busy.acquire(timeout=2))
            self.bridge._busy.release()
        self.assertFalse(self.bridge.ready()["busy"])
        self.assertEqual([event for event, _ in self.events].count("error"), 1)

    def test_invalid_failed_or_unsavable_switch_preserves_old_state(self):
        self.assertTrue(self.bridge.select_model("ollama", "old-model")["ok"])
        old = self.bridge.jarvis
        path = Path(self.temp.name) / ".jarvis" / "ui-settings.json"
        previous = path.read_bytes()
        for provider, model in (("unsupported", "x"), ("ollama", ""), (None, "x"),
                                ("ollama", None), ("ollama", "broken")):
            with self.subTest(provider=provider, model=model):
                self.assertFalse(self.bridge.select_model(provider, model)["ok"])
                self.assertIs(self.bridge.jarvis, old)
                self.assertEqual((self.bridge.provider, self.bridge.model), ("ollama", "old-model"))
                self.assertEqual(path.read_bytes(), previous)
        with mock.patch.object(self.module, "save_selection", side_effect=OSError("read-only")):
            self.assertFalse(self.bridge.select_model("ollama", "new-model")["ok"])
        self.assertIs(self.bridge.jarvis, old)
        self.assertEqual(path.read_bytes(), previous)
        self.assertEqual([event for event, _ in self.events].count("model_changed"), 1)

    def test_client_failure_never_returns_or_emits_environment_key(self):
        import config
        with mock.patch.object(config, "OPENAI_API_KEY", "synthetic-key"), \
             mock.patch.object(self.bridge, "_new_agent", side_effect=RuntimeError("bad key synthetic-key")):
            result = self.bridge.select_model("openai", "new")
            self.assertNotIn("synthetic-key", json.dumps(result))
            self.bridge.send_message("question")
            self.assertTrue(self.bridge._busy.acquire(timeout=2))
            self.bridge._busy.release()
            self.assertNotIn("synthetic-key", json.dumps(self.events))
            self.assertEqual([event for event, _ in self.events].count("turn_end"), 1)

    def test_draft_and_ignored_transcripts_reach_ui_without_starting_a_turn(self):
        with mock.patch.dict(sys.modules, {'voice.listen': types.SimpleNamespace(ContinuousListener=FakeListener)}):
            self.bridge.toggle_voice()
            listener = self.bridge.listener
            payload = {'id': 'one', 'text': 'open Chrome', 'final': True, 'accepted': False, 'reason': 'waiting_wake'}
            listener.on_partial(payload)
            self.assertIn(('speech_transcript', payload), self.events)
            self.assertEqual(self.bridge.ready()['speech_transcript'], payload)
            self.assertIsNone(self.bridge.jarvis)
            self.assertFalse(self.bridge.ready()['busy'])
            self.bridge.toggle_voice()
            count = len(self.events)
            listener.on_partial({'id': 'late', 'text': 'stale speech', 'final': False})
            self.assertEqual(len(self.events), count)

    def test_gui_wake_mode_selection_reaches_listener_and_rejects_invalid_mode(self):
        with mock.patch.dict(sys.modules, {'voice.listen': types.SimpleNamespace(ContinuousListener=FakeListener)}):
            result = self.bridge.set_wake_mode('phrase')
            self.assertTrue(result['ok'])
            self.bridge.toggle_voice()
            self.assertEqual(self.bridge.listener.wake_mode, 'phrase')
            result = self.bridge.set_wake_mode('clap')
            self.assertTrue(result['ok'])
            self.assertEqual(self.bridge.listener.wake_mode, 'clap')
            self.assertEqual(self.bridge.ready()['wake_mode'], 'clap')
            self.assertFalse(self.bridge.set_wake_mode('unknown')['ok'])
            self.assertEqual(self.bridge.ready()['wake_mode'], 'clap')

    def test_voice_toggle_emits_state_and_recovers_from_synchronous_start_failure(self):
        with mock.patch.dict(sys.modules, {"voice.listen": types.SimpleNamespace(ContinuousListener=FakeListener)}):
            with mock.patch.object(FakeListener, "start", side_effect=RuntimeError("audio driver missing")):
                self.assertFalse(self.bridge.toggle_voice())
            self.assertFalse(self.bridge.ready()["voice"])
            self.assertIsNone(self.bridge.listener)
            self.assertIn(("voice_changed", {"voice": False}), self.events)
            error = next(payload for event, payload in self.events if event == "error")
            self.assertIn("microphone", error["message"].lower())
            self.assertTrue(self.bridge.toggle_voice())
            listener = self.bridge.listener
            self.assertIn(("voice_changed", {"voice": True}), self.events)
            self.assertFalse(self.bridge.toggle_voice())
            self.assertTrue(listener.stopped)
            self.assertEqual(self.events[-2:], [("voice_changed", {"voice": False}),
                                               ("mic_state", {"state": "idle", "level": 0.0})])

    def test_async_voice_initialization_failure_disables_voice_and_is_actionable(self):
        with mock.patch.dict(sys.modules, {"voice.listen": types.SimpleNamespace(ContinuousListener=FakeListener)}):
            self.assertTrue(self.bridge.toggle_voice())
            listener = self.bridge.listener
            listener.on_error("Microphone permission denied. Open System Settings > Privacy & Security.")
        self.assertFalse(self.bridge.voice_on)
        self.assertIsNone(self.bridge.listener)
        self.assertTrue(listener.stopped)
        self.assertIn(("voice_changed", {"voice": False}), self.events)
        error = next(payload for event, payload in self.events if event == "error")
        self.assertIn("Privacy", error["message"])

    def test_old_listener_cannot_submit_or_disable_a_new_session(self):
        delivered = threading.Event()
        emit = self.bridge._emit
        def record(event, payload=None):
            emit(event, payload)
            if event == "user_voice" and payload["text"] == "current message":
                delivered.set()
        self.bridge._emit = record
        with mock.patch.dict(sys.modules, {"voice.listen": types.SimpleNamespace(ContinuousListener=FakeListener)}):
            self.bridge.toggle_voice()
            old = self.bridge.listener
            old.out.get_calls.get(timeout=1)
            self.bridge.toggle_voice()
            self.bridge.toggle_voice()
            current = self.bridge.listener
            current.out.get_calls.get(timeout=1)
            old.out.put("stale message")
            current.out.put("current message")
            self.assertTrue(delivered.wait(1))
            self.assertTrue(self.bridge._busy.acquire(timeout=2))
            self.bridge._busy.release()
            self.assertEqual([payload["text"] for event, payload in self.events if event == "user_voice"],
                             ["current message"])
            old.on_error("Old failed load must be ignored")
            old.on_state(types.SimpleNamespace(rms=1.0, listening=True))
            self.assertIs(self.bridge.listener, current)
            self.assertTrue(self.bridge.voice_on)
            self.assertFalse(any(payload and payload.get("message", "").startswith("Old")
                                 for event, payload in self.events if event == "error"))

    def test_microphone_delivery_and_state_are_suppressed_during_turns(self):
        entered, release = threading.Event(), threading.Event()
        agent = FakeAgent()
        def stream(*args, **kwargs):
            entered.set()
            release.wait(2)
            yield "done"
        agent.stream = stream
        self.bridge.jarvis = agent
        with mock.patch.dict(sys.modules, {"voice.listen": types.SimpleNamespace(ContinuousListener=FakeListener)}):
            self.bridge.toggle_voice()
            listener = self.bridge.listener
            listener.out.get_calls.get(timeout=1)
            try:
                self.bridge.send_message("typed question")
                self.assertTrue(entered.wait(1))
                baseline = len(self.events)
                listener.on_state(types.SimpleNamespace(rms=1.0, listening=True))
                listener.out.put("during turn")
                listener.out.get_calls.get(timeout=1)  # next receive proves the prior delivery was processed
                self.assertEqual(len(self.events), baseline)
                self.assertTrue(listener.is_suppressed())
            finally:
                release.set()
                if self.bridge._busy.acquire(timeout=2):
                    self.bridge._busy.release()

    def test_window_close_shutdown_stops_voice_speech_and_rejects_new_work(self):
        class Event:
            def __init__(self):
                self.handlers = []
            def __iadd__(self, handler):
                self.handlers.append(handler)
                return self
        window = types.SimpleNamespace(events=types.SimpleNamespace(closed=Event()))
        self.bridge.attach(window)
        with mock.patch.dict(sys.modules, {"voice.listen": types.SimpleNamespace(ContinuousListener=FakeListener)}), \
             mock.patch.object(self.module, "stop_speech") as stop:
            self.bridge.toggle_voice()
            listener = self.bridge.listener
            self.assertIn(self.bridge.shutdown, window.events.closed.handlers)
            self.bridge.interrupt()
            self.assertTrue(self.bridge.voice_on)
            self.assertIn(("speech_stopped", None), self.events)
            self.bridge.shutdown()
            self.bridge.shutdown()  # idempotent
            self.assertTrue(listener.stopped)
            self.assertIsNone(self.bridge.listener)
            self.assertFalse(self.bridge.voice_on)
            self.assertGreaterEqual(stop.call_count, 2)
            self.assertFalse(self.bridge.toggle_voice())
            self.assertFalse(self.bridge.send_message("closed")["ok"])
            self.assertFalse(self.bridge.select_model("ollama", "new")["ok"])
            self.assertFalse(self.bridge.reset()["ok"])

    def test_interrupt_cancels_remaining_speech_but_keeps_streaming_turn(self):
        spoken = []
        finished = threading.Event()
        agent = FakeAgent()
        agent.stream = lambda *args, **kwargs: iter(["First sentence.", "Second sentence.", "tail"])
        self.bridge.jarvis = agent
        def speech(text):
            spoken.append(text)
            self.bridge.interrupt()
        emit = self.bridge._emit
        def record(event, payload=None):
            emit(event, payload)
            if event == "turn_end":
                finished.set()
        self.bridge._emit = record
        with mock.patch.object(self.module, "speak", side_effect=speech), \
             mock.patch.object(self.module, "stop_speech") as stop:
            self.bridge.send_message("question", voiced=True)
            self.assertTrue(finished.wait(1))
            self.assertTrue(self.bridge._busy.acquire(timeout=2))
            self.bridge._busy.release()
            stop.assert_called_once()
        self.assertEqual(spoken, ["First sentence."])
        self.assertEqual([payload["text"] for event, payload in self.events if event == "chunk"],
                         ["First sentence.", "Second sentence.", "tail"])
        self.assertNotIn("error", [event for event, _ in self.events])

    def test_failed_thread_start_releases_busy_without_starting_a_turn(self):
        with mock.patch.object(self.module.threading, "Thread") as thread:
            thread.return_value.start.side_effect = RuntimeError("cannot start worker")
            result = self.bridge.send_message("question")
        self.assertFalse(result["ok"])
        self.assertIn("worker", result["error"])
        self.assertFalse(self.bridge.ready()["busy"])
        self.assertNotIn("turn_start", [event for event, _ in self.events])

    def test_shell_tool_confirmation_is_bound_to_the_current_desktop_turn(self):
        from webui.permissions import request_shell_confirmation
        dialog = mock.Mock(return_value=False)
        self.bridge.window = types.SimpleNamespace(create_confirmation_dialog=dialog)
        agent = FakeAgent()
        def stream(text, on_tool=None):
            approved = request_shell_confirmation('echo OK')
            yield 'approved' if approved else 'denied'
        agent.stream = stream
        self.bridge.jarvis = agent
        self.bridge.send_message('question')
        self.assertTrue(self.bridge._busy.acquire(timeout=2))
        self.bridge._busy.release()
        dialog.assert_called_once()
        self.assertIn('echo OK', dialog.call_args.args[1])
        self.assertIn(('chunk', {'text': 'denied'}), self.events)
        self.assertIsNone(request_shell_confirmation('echo OK'))

    def test_js_events_are_json_encoded_not_interpolated_as_code(self):
        window = types.SimpleNamespace(evaluate_js=mock.Mock())
        bridge = self.module.Bridge()
        bridge.attach(window)
        payload = {"text": "quoted \"message\"\nwith Unicode —"}
        bridge._emit("chunk", payload)
        script = window.evaluate_js.call_args.args[0]
        self.assertEqual(script, "window.jarvisEvent(" + json.dumps("chunk") + ", "
                         + json.dumps(payload, ensure_ascii=False) + ")")

    def test_failed_tts_launch_clears_speaking_guard_so_microphone_can_resume(self):
        speaking = threading.Event()
        def fail_speech(text):
            speaking.set()
            raise OSError("say unavailable")
        fake = types.SimpleNamespace(speak=fail_speech, stop=speaking.clear)
        self.bridge.jarvis = FakeAgent()
        with mock.patch.dict(sys.modules, {"voice.speak": fake}), \
             mock.patch.object(self.module, "speak", self.real_speak):
            self.bridge.send_message("question", voiced=True)
            self.assertTrue(self.bridge._busy.acquire(timeout=2))
            self.bridge._busy.release()
        self.assertFalse(speaking.is_set())
        self.assertIn("error", [event for event, _ in self.events])
        self.assertIn("turn_end", [event for event, _ in self.events])


if __name__ == "__main__":
    unittest.main()
