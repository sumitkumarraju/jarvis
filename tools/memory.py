import json
from pathlib import Path
from langchain_core.tools import tool

MEM_FILE = Path.home() / ".jarvis" / "memory.json"


def _load() -> dict:
    if not MEM_FILE.exists():
        return {}
    try:
        return json.loads(MEM_FILE.read_text())
    except Exception:
        return {}


def _save(data: dict) -> None:
    MEM_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEM_FILE.write_text(json.dumps(data, indent=2))


@tool
def remember(key: str, value: str) -> str:
    """Save a fact to long-term memory under a key (e.g. 'home_address', 'project_path')."""
    data = _load()
    data[key] = value
    _save(data)
    return f"Remembered '{key}'."


@tool
def recall(key: str) -> str:
    """Look up a fact by key. Use list_memory to see available keys."""
    data = _load()
    if key not in data:
        return f"No memory for '{key}'."
    return data[key]


@tool
def list_memory() -> str:
    """List all stored memory keys."""
    data = _load()
    if not data:
        return "(empty)"
    return ", ".join(sorted(data.keys()))


@tool
def forget(key: str) -> str:
    """Delete a memory by key."""
    data = _load()
    if key not in data:
        return f"No memory for '{key}'."
    del data[key]
    _save(data)
    return f"Forgot '{key}'."
