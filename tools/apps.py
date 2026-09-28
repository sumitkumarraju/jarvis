import subprocess
from typing import Literal
from langchain_core.tools import tool


def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        return f"Error: {r.stderr.strip()}"
    return r.stdout.strip() or "OK"


@tool
def open_app(app_name: str) -> str:
    """Open a macOS application by name (e.g. 'Safari', 'Notes', 'Visual Studio Code')."""
    r = subprocess.run(["open", "-a", app_name], capture_output=True, text=True)
    return r.stderr.strip() or f"Opened {app_name}"


@tool
def quit_app(app_name: str) -> str:
    """Quit a macOS application by name."""
    return _osascript(f'tell application "{app_name}" to quit')


@tool
def switch_to_app(app_name: str) -> str:
    """Bring an application to the foreground."""
    return _osascript(f'tell application "{app_name}" to activate')


@tool
def list_running_apps() -> str:
    """List currently running visible applications."""
    return _osascript(
        'tell application "System Events" to get name of (every process whose background only is false)'
    )


@tool
def spotify_playback(action: Literal["play", "pause", "next", "previous"]) -> str:
    """Control Spotify playback immediately: play, pause, next, or previous."""
    commands = {
        "play": "play",
        "pause": "pause",
        "next": "next track",
        "previous": "previous track",
    }
    subprocess.run(["open", "-a", "Spotify"], check=False, capture_output=True, text=True)
    return _osascript(f'tell application "Spotify" to {commands[action]}')
