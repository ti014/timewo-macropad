"""Execute explicit mappings; paste Unicode text without IME key composition."""

import ctypes
import shutil
import subprocess
import time
import webbrowser
from pathlib import Path
from typing import Any

from pynput.keyboard import Controller, Key
from PySide6.QtGui import QGuiApplication

from .config import Action, parse_hotkey, parse_sequence


class Executor:
    """Keyboard and application-launch backend with injectable test controller."""

    def __init__(self, keyboard: Any = None) -> None:
        """Initialize the keyboard backend.

        Args:
            keyboard: Test controller; defaults to the Windows keyboard controller.
        """
        self._keyboard = keyboard if keyboard is not None else Controller()
        self._held: dict[int, Key] = {}

    @staticmethod
    def _copy_screenshot() -> None:
        """Capture the primary display and put it on the system clipboard."""
        app = QGuiApplication.instance()
        if app is None:
            raise OSError("Screenshot requires the Macropad application to be running.")
        screen = app.primaryScreen()
        if screen is None:
            raise OSError("No display was found.")
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            raise OSError("The screen could not be captured.")
        app.clipboard().setPixmap(pixmap)

    @staticmethod
    def _lock_workstation() -> None:
        """Lock Windows through its native API instead of injecting Win+L."""
        try:
            locked = bool(ctypes.windll.user32.LockWorkStation())
        except AttributeError as exc:
            raise OSError("Khóa màn hình chỉ được hỗ trợ trên Windows.") from exc
        if not locked:
            raise OSError("Windows không cho phép khóa màn hình.")

    def hold(self, button: int, action: Action) -> None:
        """Own each held modifier by physical button, ignoring duplicate presses."""
        action.validate()
        if action.kind != "hold_key":
            raise ValueError("Hành động này không phải Giữ phím.")
        if button in self._held:
            return
        key = {"ctrl": Key.ctrl, "alt": Key.alt, "shift": Key.shift, "win": Key.cmd}[action.value.lower()]
        already_held = key in self._held.values()
        self._held[button] = key
        if not already_held:
            self._keyboard.press(key)

    def release(self, button: int) -> None:
        """Only release a modifier owned by this button; retain failed releases."""
        key = self._held.get(button)
        if key is None:
            return
        if list(self._held.values()).count(key) == 1:
            self._keyboard.release(key)
        del self._held[button]

    def release_all(self) -> None:
        """Attempt all releases; keep failed keys tracked for another attempt."""
        errors = []
        for key in set(self._held.values()):
            try:
                self._keyboard.release(key)
            except (OSError, ValueError) as exc:
                errors.append(exc)
            else:
                self._held = {button: held for button, held in self._held.items() if held != key}
        if errors:
            raise errors[0]

    def execute(self, action: Action) -> None:
        """Perform one validated mapping in the currently focused application.

        Args:
            action: Explicitly selected button mapping.

        Raises:
            ValueError: If the mapping is invalid.
            OSError: If an executable or browser cannot be launched.
        """
        action.validate()
        if action.kind == "lock_screen":
            self._lock_workstation()
            return
        if action.kind == "close_app":
            self.execute(Action("hotkey", "Alt+F4"))
            return
        if action.kind == "screenshot":
            self._copy_screenshot()
            return
        if action.kind == "sequence":
            for step in parse_sequence(action.value):
                if isinstance(step, int):
                    # shortcut: blocks the GUI for the wait (max 3 s); move to a worker if longer.
                    time.sleep(step / 1000)
                else:
                    self._press_chord(step)
            return
        if action.kind == "hotkey":
            keys = parse_hotkey(action.value)
            if keys == ["cmd", "l"]:
                self._lock_workstation()
                return
            self._press_chord(keys)
        elif action.kind == "text":
            app = QGuiApplication.instance()
            if app is None:
                raise OSError("Dán văn bản cần ứng dụng Macropad đang chạy.")
            app.clipboard().setText(action.value)
            self._press_chord(["ctrl", "v"])
        elif action.kind == "app":
            path = Path(action.value)
            if not path.is_file():
                raise FileNotFoundError(f"Application not found: {path}")
            subprocess.Popen([str(path)], shell=False, cwd=str(path.parent))
        elif action.kind == "script":
            path = Path(action.value)
            if not path.is_file():
                raise FileNotFoundError(f"Script not found: {path}")
            subprocess.Popen(script_command(path), shell=False, cwd=str(path.parent))
        elif action.kind == "url" and not webbrowser.open(action.value):
            raise OSError("The default browser could not be opened.")

    def _press_chord(self, names: list[str]) -> None:
        """Press and release one normalized chord safely."""
        keys = [getattr(Key, key) if len(key) > 1 else key for key in names]
        pressed = []
        try:
            for key in keys:
                if key in self._held.values():
                    continue
                pressed.append(key)
                self._keyboard.press(key)
        finally:
            # Attempt every release even if one release fails.
            errors = []
            for key in reversed(pressed):
                try:
                    self._keyboard.release(key)
                except (OSError, ValueError) as exc:
                    errors.append(exc)
            if errors:
                raise errors[0]



def script_command(path: Path) -> list[str]:
    """Build the interpreter command for one script file, never through a shell string.

    Raises:
        OSError: If the interpreter the file needs is not installed.
    """
    suffix = path.suffix.lower()
    if suffix in {".bat", ".cmd"}:
        return ["cmd.exe", "/c", str(path)]
    if suffix == ".ps1":
        return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(path)]
    # The packaged app has no Python of its own; use the one installed on this computer.
    names = ("pyw", "pythonw", "py", "python") if suffix == ".pyw" else ("py", "python")
    interpreter = next((found for name in names if (found := shutil.which(name))), None)
    if interpreter is None:
        raise OSError("Không tìm thấy Python trên máy để chạy script .py.")
    return [interpreter, str(path)]
