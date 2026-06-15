from .web import web_search, fetch_page
from .apps import open_app, quit_app, list_running_apps, switch_to_app
from .shell import run_shell
from .files import list_dir, read_file, write_file, find_files
from .keyboard import type_text, press_keys, mouse_click, mouse_move, get_screen_size
from .screen import take_screenshot
from .system import (
    set_volume, mute_volume, unmute_volume, system_notification,
    lock_screen, get_battery, get_clipboard, set_clipboard,
)
from .memory import remember, recall, list_memory, forget

ALL_TOOLS = [
    web_search, fetch_page,
    open_app, quit_app, list_running_apps, switch_to_app,
    run_shell,
    list_dir, read_file, write_file, find_files,
    type_text, press_keys, mouse_click, mouse_move, get_screen_size,
    take_screenshot,
    set_volume, mute_volume, unmute_volume, system_notification,
    lock_screen, get_battery, get_clipboard, set_clipboard,
    remember, recall, list_memory, forget,
]
