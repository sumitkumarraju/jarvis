import subprocess
import time
from pathlib import Path
from langchain_core.tools import tool

SHOTS_DIR = Path.home() / "Pictures" / "jarvis-shots"


@tool
def take_screenshot(region: str = "full") -> str:
    """Take a screenshot. region: 'full' for whole screen, 'select' for interactive selection.
    Saves to ~/Pictures/jarvis-shots/ and returns the path."""
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = SHOTS_DIR / f"shot-{ts}.png"
    args = ["screencapture", "-x"]
    if region == "select":
        args = ["screencapture", "-i"]
    args.append(str(path))
    r = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return f"Error: {r.stderr.strip()}"
    return str(path)
