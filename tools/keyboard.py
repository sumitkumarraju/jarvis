from langchain_core.tools import tool

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    _ENABLED = True
except Exception as _e:
    _ENABLED = False
    _IMPORT_ERR = str(_e)


def _check() -> str | None:
    if not _ENABLED:
        return f"pyautogui unavailable: {_IMPORT_ERR}"
    return None


@tool
def type_text(text: str) -> str:
    """Type text at the current cursor position (as if from the keyboard)."""
    if err := _check(): return err
    pyautogui.typewrite(text, interval=0.01)
    return f"Typed {len(text)} chars"


@tool
def press_keys(keys: str) -> str:
    """Press a key or hotkey combo. Examples: 'enter', 'escape', 'cmd+space', 'cmd+shift+4'."""
    if err := _check(): return err
    parts = [k.strip().lower() for k in keys.split("+")]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return f"Pressed {keys}"


@tool
def mouse_click(x: int | None = None, y: int | None = None, button: str = "left", clicks: int = 1) -> str:
    """Click the mouse. Omit x/y to click at current position. button: left/right/middle."""
    if err := _check(): return err
    pyautogui.click(x=x, y=y, clicks=clicks, button=button)
    pos = f"({x},{y})" if x is not None else "current pos"
    return f"{button} click x{clicks} at {pos}"


@tool
def mouse_move(x: int, y: int) -> str:
    """Move the mouse to absolute screen coordinates."""
    if err := _check(): return err
    pyautogui.moveTo(x, y, duration=0.15)
    return f"Moved to ({x},{y})"


@tool
def get_screen_size() -> str:
    """Return screen size in pixels."""
    if err := _check(): return err
    w, h = pyautogui.size()
    return f"{w}x{h}"
