import subprocess
from pathlib import Path
from langchain_core.tools import tool

from config import WORKDIR


def _resolve(p: str) -> Path:
    path = Path(p).expanduser()
    if not path.is_absolute():
        path = WORKDIR / path
    return path


@tool
def list_dir(path: str = ".") -> str:
    """List files and folders at a path."""
    p = _resolve(path)
    if not p.exists():
        return f"Not found: {p}"
    items = sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))
    return "\n".join(f"{'d' if i.is_dir() else 'f'} {i.name}" for i in items[:200])


@tool
def read_file(path: str, max_chars: int = 4000) -> str:
    """Read a text file."""
    p = _resolve(path)
    if not p.exists():
        return f"Not found: {p}"
    try:
        text = p.read_text(errors="replace")
        return text[:max_chars] + ("..." if len(text) > max_chars else "")
    except Exception as e:
        return f"Error: {e}"


@tool
def write_file(path: str, content: str) -> str:
    """Write text to a file (overwrites). Creates parents."""
    p = _resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    return f"Wrote {len(content)} chars to {p}"


@tool
def find_files(pattern: str, root: str = ".") -> str:
    """Find files by name pattern under a root, e.g. '*.pdf'."""
    p = _resolve(root)
    try:
        r = subprocess.run(
            ["find", str(p), "-iname", pattern, "-not", "-path", "*/.*"],
            capture_output=True, text=True, timeout=20,
        )
        lines = [l for l in r.stdout.splitlines() if l][:100]
        return "\n".join(lines) or "No matches."
    except Exception as e:
        return f"Error: {e}"
