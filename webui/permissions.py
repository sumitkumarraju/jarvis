"""Per-turn confirmation callback; never globally changes CLI safety prompts."""
from contextlib import contextmanager
from contextvars import ContextVar

_handler = ContextVar('jarvis_shell_confirmation', default=None)


@contextmanager
def shell_confirmation(handler):
    token = _handler.set(handler)
    try:
        yield
    finally:
        _handler.reset(token)


def request_shell_confirmation(command: str) -> bool | None:
    handler = _handler.get()
    if handler is None:
        return None  # CLI uses the original terminal prompt.
    try:
        return handler(command) is True
    except Exception:
        return False
