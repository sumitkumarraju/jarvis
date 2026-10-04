import subprocess
from langchain_core.tools import tool
from rich.console import Console
from rich.prompt import Confirm

from config import CONFIRM_SHELL, WORKDIR
from webui.permissions import request_shell_confirmation

console = Console()

DANGEROUS = ("rm -rf", "mkfs", "dd if=", ":(){", "shutdown", "reboot", "sudo rm")


@tool
def run_shell(command: str) -> str:
    """Run a shell command on macOS. Returns combined stdout/stderr.
    Dangerous commands and writes prompt the user for confirmation."""
    if any(d in command for d in DANGEROUS):
        return f"Refused: command matches dangerous pattern. Ask the user to run manually: {command}"

    if CONFIRM_SHELL:
        approved = request_shell_confirmation(command)
        if approved is None:
            console.print(f"[yellow]Run shell:[/yellow] [bold]{command}[/bold]")
            approved = Confirm.ask("Allow?", default=False)
        if not approved:
            return "User denied execution."

    try:
        r = subprocess.run(
            command, shell=True, capture_output=True, text=True, timeout=60, cwd=str(WORKDIR)
        )
        out = (r.stdout or "") + (r.stderr or "")
        return out.strip()[:4000] or f"(exit {r.returncode}, no output)"
    except subprocess.TimeoutExpired:
        return "Timed out after 60s."
    except Exception as e:
        return f"Error: {e}"
