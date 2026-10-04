"""Portable launcher checks without installing dependencies or touching the desktop."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]


class LauncherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='jarvis launch ')
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'project with spaces'
        self.project.mkdir()
        interpreter = self.project / '.venv/bin/python'
        interpreter.parent.mkdir(parents=True)
        interpreter.write_text('#!/bin/bash\nprintf "cwd=%s\\n" "$PWD"\nprintf "arg=%s\\n" "$@"\n')
        interpreter.chmod(0o755)

    def test_launcher_uses_its_own_folder_and_forwards_arguments(self):
        shutil.copy(ROOT / 'jarvis', self.project / 'jarvis')
        result = subprocess.run(['bash', str(self.project / 'jarvis'), '--text'], cwd='/tmp', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(f'cwd={self.project}', result.stdout)
        self.assertIn('arg=main.py\narg=--text', result.stdout)

    def test_double_click_launcher_starts_gui_with_voice_enabled(self):
        command = ROOT / 'Jarvis.command'
        self.assertTrue(command.exists(), 'Double-click desktop launcher is missing')
        shutil.copy(command, self.project / command.name)
        shutil.copy(ROOT / 'jarvis', self.project / 'jarvis')
        (self.project / 'jarvis').chmod(0o755)
        result = subprocess.run(['bash', str(self.project / command.name)], cwd='/tmp', capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('arg=main.py', result.stdout)
        self.assertNotIn('arg=--no-voice', result.stdout)


class WindowLifecycleTests(unittest.TestCase):
    def test_closing_window_shuts_down_voice_and_speech(self):
        console_module = types.ModuleType('rich.console')
        console_module.Console = MagicMock()
        webview = types.ModuleType('webview')
        window = MagicMock()
        closed_event = window.events.closed
        webview.create_window = MagicMock(return_value=window)
        webview.start = MagicMock()
        from webui.bridge import Bridge
        bridge_module = types.ModuleType('webui.bridge')
        bridge = Bridge()
        bridge.shutdown = MagicMock()
        bridge.toggle_voice = MagicMock()
        bridge_module.Bridge = MagicMock(return_value=bridge)
        with patch.dict(sys.modules, {'rich': types.ModuleType('rich'), 'rich.console': console_module, 'webview': webview, 'webui.bridge': bridge_module}):
            spec = importlib.util.spec_from_file_location('jarvis_main_test', ROOT / 'main.py')
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module.app(start_voice=False)
        closed_event.__iadd__.assert_called_once_with(bridge.shutdown)
        bridge.toggle_voice.assert_not_called()
        webview.start.assert_called_once_with(debug=False)


if __name__ == '__main__':
    unittest.main()
