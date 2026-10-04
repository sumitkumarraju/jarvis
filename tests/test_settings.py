import importlib
import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class PreferenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "ui-settings.json"
        self.env = mock.patch.dict(os.environ, {}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_atomic_preference_roundtrip_persists_only_provider_and_model(self):
        settings = importlib.import_module("webui.settings")
        with mock.patch.object(settings.os, "replace", wraps=os.replace) as replace:
            settings.save_selection("omniroute", "my-model", self.path)
        replace.assert_called_once()
        self.assertEqual(json.loads(self.path.read_text()),
                         {"provider": "omniroute", "model": "my-model"})
        self.assertEqual(settings.load_selection(self.path), ("omniroute", "my-model"))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_environment_overrides_saved_selection_without_changing_endpoints(self):
        settings = importlib.import_module("webui.settings")
        settings.save_selection("omniroute", "saved-api", self.path)
        with mock.patch.dict(os.environ, {"OPENAI_MODEL": "env-api"}):
            self.assertEqual(settings.load_selection(self.path), ("omniroute", "env-api"))
        with mock.patch.dict(os.environ, {"JARVIS_PROVIDER": "ollama", "JARVIS_MODEL": "env-local"}):
            self.assertEqual(settings.load_selection(self.path), ("ollama", "env-local"))
        with mock.patch.dict(os.environ, {"JARVIS_PROVIDER": "ollama"}):
            self.assertEqual(settings.load_selection(self.path), ("ollama", settings.config.OLLAMA_MODEL))
        self.assertEqual(json.loads(self.path.read_text())["model"], "saved-api")

    def test_malformed_preferences_are_ignored(self):
        settings = importlib.import_module("webui.settings")
        expected = ("ollama", "local-default")
        with mock.patch.multiple(settings.config, JARVIS_PROVIDER="ollama", OLLAMA_MODEL="local-default"):
            for content in ("broken json", "[]", "null", "{}", '{"provider":"unknown","model":"m"}',
                            '{"provider":"ollama","model":3}', '{"provider":"ollama","model":""}',
                            "x" * 5000):
                with self.subTest(content=content[:50]):
                    self.path.write_text(content)
                    self.assertEqual(settings.load_selection(self.path), expected)

    def test_failed_atomic_save_preserves_previous_file_and_cleans_temporary_file(self):
        settings = importlib.import_module("webui.settings")
        settings.save_selection("ollama", "old", self.path)
        with mock.patch.object(settings.os, "replace", side_effect=OSError("read-only")):
            with self.assertRaises(OSError):
                settings.save_selection("openai", "new", self.path)
        self.assertEqual(settings.load_selection(self.path), ("ollama", "old"))
        self.assertEqual(list(self.path.parent.iterdir()), [self.path])


class DiscoveryTests(unittest.TestCase):
    def test_bridge_discovers_installed_or_remote_model_names_with_bounded_get(self):
        settings = importlib.import_module("webui.settings")
        from webui.bridge import Bridge
        for provider, payload, expected, url in (
            ("ollama", {"models": [{"name": "local:latest"}, {"name": "local:latest"}]},
             ["local:latest"], "http://local.example:11434/api/tags"),
            ("openai", {"data": [{"id": "remote/model"}]}, ["remote/model"], "http://api.example/v1/models"),
            ("omniroute", {"data": [{"id": "remote/model"}]}, ["remote/model"], "http://api.example/v1/models"),
            ("claude", {"data": [{"id": "remote/model"}]}, ["remote/model"], "http://api.example/v1/models"),
        ):
            with self.subTest(provider=provider), tempfile.TemporaryDirectory() as home:
                with mock.patch.dict(os.environ, {"HOME": home}, clear=True), \
                     mock.patch.multiple(settings.config, OLLAMA_HOST="http://local.example:11434/",
                                         OPENAI_BASE_URL="http://api.example/v1/", OPENAI_API_KEY="secret-value"), \
                     mock.patch.object(settings, "build_opener", create=True) as make_opener:
                    opener = make_opener.return_value
                    opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
                    result = Bridge().list_models(provider)
                    self.assertEqual(result, {"models": expected, "provider": provider, "error": None})
                    request = opener.open.call_args.args[0]
                    self.assertEqual(request.full_url, url)
                    self.assertEqual(request.get_method(), "GET")
                    self.assertLessEqual(opener.open.call_args.kwargs["timeout"], 10)
                    if provider == "ollama":
                        self.assertNotIn("Authorization", request.headers)
                    else:
                        self.assertEqual(request.headers["Authorization"], "Bearer secret-value")
                    self.assertNotIn("secret-value", json.dumps(result))

    def test_missing_key_bad_schema_and_unavailable_service_are_safe_errors(self):
        settings = importlib.import_module("webui.settings")
        with mock.patch.object(settings.config, "OPENAI_API_KEY", ""), \
             mock.patch.object(settings, "build_opener") as build:
            result = settings.discover_models("openai")
            self.assertEqual(result["models"], [])
            self.assertIn("OPENAI_API_KEY", result["error"])
            build.assert_not_called()
        for response in (b"not json", b"{}", b'{"models": null}', b"x" * (1024 * 1024 + 1)):
            with self.subTest(response=response[:30]), mock.patch.object(settings, "build_opener") as build:
                build.return_value.open.return_value = io.BytesIO(response)
                result = settings.discover_models("ollama")
                self.assertTrue(result["error"])
                self.assertEqual(result["models"], [])
        with mock.patch.object(settings, "build_opener") as build:
            build.return_value.open.side_effect = RuntimeError("server revealed secret-value")
            result = settings.discover_models("ollama")
            self.assertNotIn("secret-value", result["error"])
            self.assertTrue(result["error"])
        with mock.patch.object(settings, "build_opener") as build:
            self.assertTrue(settings.discover_models("bad-provider")["error"])
            build.assert_not_called()

    def test_provider_metadata_hides_endpoint_credentials_and_query(self):
        import config
        with mock.patch.object(config, "OPENAI_BASE_URL", "http://user:password@localhost/v1?api_key=secret-value"), \
             mock.patch.object(config, "OPENAI_API_KEY", "secret-value"):
            info = config.provider_info()
        self.assertEqual(info[1]["endpoint"], "http://localhost/v1")
        self.assertTrue(info[1]["key_configured"])
        self.assertNotIn("password", json.dumps(info))
        self.assertNotIn("secret-value", json.dumps(info))

    def test_discovery_does_not_forward_credentials_to_redirect_target(self):
        settings = importlib.import_module("webui.settings")
        requests = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                requests.append((self.path, self.headers.get("Authorization")))
                if self.path == "/v1/models":
                    self.send_response(302)
                    self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/trap")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b'{"data": []}')
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with mock.patch.multiple(settings.config, OPENAI_BASE_URL=f"http://127.0.0.1:{server.server_port}/v1",
                                     OPENAI_API_KEY="synthetic-key"):
                result = settings.discover_models("openai")
            self.assertEqual(requests, [("/v1/models", "Bearer synthetic-key")])
            self.assertTrue(result["error"])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
