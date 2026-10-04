"""Desktop shell approvals must be visible and fail closed; CLI keeps its prompt."""
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

from webui.permissions import shell_confirmation

ROOT = Path(__file__).resolve().parents[1]


class ShellApprovalTests(unittest.TestCase):
    def setUp(self):
        self.confirm = Mock(return_value=False)
        self.run = Mock(return_value=types.SimpleNamespace(stdout='OK', stderr='', returncode=0))
        modules = {
            'langchain_core.tools': types.SimpleNamespace(tool=lambda function: function),
            'rich.console': types.SimpleNamespace(Console=lambda: types.SimpleNamespace(print=lambda *args: None)),
            'rich.prompt': types.SimpleNamespace(Confirm=types.SimpleNamespace(ask=self.confirm)),
        }
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location('shell_approval_test', ROOT / 'tools/shell.py')
            self.shell = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.shell)
        self.shell.CONFIRM_SHELL = True
        self.patch = patch.object(self.shell.subprocess, 'run', self.run)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_gui_approval_replaces_hidden_terminal_prompt(self):
        approve = Mock(return_value=True)
        with shell_confirmation(approve):
            self.assertEqual(self.shell.run_shell('echo OK'), 'OK')
        approve.assert_called_once_with('echo OK')
        self.confirm.assert_not_called()
        self.run.assert_called_once()

    def test_gui_denial_never_runs_the_command(self):
        with shell_confirmation(lambda command: False):
            self.assertEqual(self.shell.run_shell('echo OK'), 'User denied execution.')
        self.run.assert_not_called()
        self.confirm.assert_not_called()

    def test_cli_prompt_is_restored_after_gui_scope(self):
        with shell_confirmation(lambda command: False):
            self.shell.run_shell('echo OK')
        self.shell.run_shell('echo OK')
        self.confirm.assert_called_once_with('Allow?', default=False)

    def test_dangerous_command_is_refused_even_with_gui_approval(self):
        approve = Mock(return_value=True)
        with shell_confirmation(approve):
            self.assertIn('Refused:', self.shell.run_shell('rm -rf /'))
        approve.assert_not_called()
        self.run.assert_not_called()

    def test_broken_dialog_fails_closed(self):
        approve = Mock(side_effect=RuntimeError('window closed'))
        with shell_confirmation(approve):
            self.assertEqual(self.shell.run_shell('echo OK'), 'User denied execution.')
        self.run.assert_not_called()


if __name__ == '__main__':
    unittest.main()
