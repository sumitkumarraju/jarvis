import subprocess
from langchain_core.tools import tool


def _osa(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    return r.stderr.strip() if r.returncode != 0 else (r.stdout.strip() or "OK")


@tool
def set_volume(level: int) -> str:
    """Set system volume (0-100)."""
    level = max(0, min(100, level))
    return _osa(f"set volume output volume {level}") and f"Volume → {level}"


@tool
def mute_volume() -> str:
    """Mute system audio."""
    return _osa("set volume with output muted")


@tool
def unmute_volume() -> str:
    """Unmute system audio."""
    return _osa("set volume without output muted")


@tool
def system_notification(title: str, message: str) -> str:
    """Show a macOS notification banner."""
    safe_t = title.replace('"', "'")
    safe_m = message.replace('"', "'")
    return _osa(f'display notification "{safe_m}" with title "{safe_t}"')


@tool
def lock_screen() -> str:
    """Lock the screen."""
    r = subprocess.run(
        ["pmset", "displaysleepnow"], capture_output=True, text=True
    )
    return r.stderr.strip() or "Screen locked"


@tool
def get_battery() -> str:
    """Return battery percentage and charging state."""
    r = subprocess.run(["pmset", "-g", "batt"], capture_output=True, text=True)
    return r.stdout.strip() or "Unavailable"


@tool
def get_clipboard() -> str:
    """Read the macOS clipboard."""
    r = subprocess.run(["pbpaste"], capture_output=True, text=True)
    return r.stdout


@tool
def set_clipboard(text: str) -> str:
    """Write text to the macOS clipboard."""
    p = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
    p.communicate(text.encode())
    return f"Copied {len(text)} chars"
