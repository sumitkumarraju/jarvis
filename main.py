import argparse
import sys
from pathlib import Path

from rich.console import Console

console = Console()
WEBUI_DIR = Path(__file__).parent / "webui"


def text_loop() -> None:
    """Plain text REPL with streaming output."""
    from agent.jarvis import Jarvis
    j = Jarvis()
    console.print("[bold cyan]Jarvis[/bold cyan] (text). 'exit' to quit, 'reset' to clear context.")
    while True:
        try:
            user = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); break
        if not user: continue
        if user.lower() in {"exit", "quit"}: break
        if user.lower() == "reset":
            j.reset(); console.print("[dim]cleared[/dim]"); continue
        console.print("[bold green]Jarvis:[/bold green] ", end="")
        for chunk in j.stream(user, on_tool=lambda n, a: console.print(f"\n[dim magenta]→ {n}({a})[/dim magenta]")):
            console.print(chunk, end="")
        console.print()


def app(start_voice: bool) -> None:
    """Launch the desktop webview UI."""
    import webview
    from webui.bridge import Bridge

    bridge = Bridge()
    window = webview.create_window(
        "JARVIS",
        str(WEBUI_DIR / "index.html"),
        js_api=bridge,
        width=1200,
        height=780,
        min_size=(900, 600),
        background_color="#050813",
        text_select=True,
        easy_drag=False,
    )
    bridge.attach(window)

    def on_loaded():
        if start_voice:
            bridge.toggle_voice()
    window.events.loaded += on_loaded

    webview.start(debug=False)


def main() -> None:
    ap = argparse.ArgumentParser(prog="jarvis")
    ap.add_argument("--text", action="store_true", help="plain text REPL (no window)")
    ap.add_argument("--no-voice", action="store_true", help="start with voice OFF")
    args = ap.parse_args()

    if args.text:
        text_loop()
        return
    app(start_voice=not args.no_voice)


if __name__ == "__main__":
    sys.exit(main())
