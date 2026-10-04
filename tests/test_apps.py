"""Native app launch failures must not be reported as successful actions."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class NativeAppTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / 'tools/apps.py'
        with patch.dict(sys.modules, {'langchain_core.tools': types.SimpleNamespace(tool=lambda fn: fn)}):
            spec = importlib.util.spec_from_file_location('native_apps_test', path)
            self.apps = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.apps)

    def test_open_failure_is_a_clear_error_not_a_success_reply(self):
        failure = types.SimpleNamespace(returncode=1, stderr='Application not found')
        with patch.object(self.apps.subprocess, 'run', return_value=failure):
            self.assertTrue(self.apps.open_app('Unknown').startswith('Error:'))

    def test_open_uses_argument_list_without_shell_and_reports_success(self):
        success = types.SimpleNamespace(returncode=0, stderr='')
        with patch.object(self.apps.subprocess, 'run', return_value=success) as run:
            self.assertEqual(self.apps.open_app('Google Chrome'), 'Opened Google Chrome')
        self.assertEqual(run.call_args.args[0], ['open', '-a', 'Google Chrome'])
        self.assertFalse(run.call_args.kwargs.get('shell', False))


if __name__ == '__main__':
    unittest.main()
