"""Exercise side-effect boundaries using fakes instead of OS keyboard events."""

from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from pynput.keyboard import Key

from macropad.actions import Executor
from macropad.config import Action, Config, load_config, save_config
from macropad.transport import Connection, available_ports


def test_hotkey_press_release_order() -> None:
    """Release every key in reverse order."""
    keyboard = Mock()
    Executor(keyboard).execute(Action("hotkey", "Ctrl+Shift+S"))
    assert [call.args[0] for call in keyboard.press.call_args_list] == [Key.ctrl, Key.shift, "s"]
    assert [call.args[0] for call in keyboard.release.call_args_list] == ["s", Key.shift, Key.ctrl]


def test_close_app_action_sends_alt_f4() -> None:
    """The named close action works without relying on the recorder."""
    keyboard = Mock()
    Executor(keyboard).execute(Action("close_app"))
    assert [call.args[0] for call in keyboard.press.call_args_list] == [Key.alt, Key.f4]
    assert [call.args[0] for call in keyboard.release.call_args_list] == [Key.f4, Key.alt]


def test_lock_screen_action_calls_windows_api() -> None:
    """Lock screen uses the native API rather than typing a literal L."""
    with patch("macropad.actions.ctypes.windll.user32.LockWorkStation", return_value=1) as lock:
        Executor(Mock()).execute(Action("lock_screen"))
    lock.assert_called_once_with()


def test_legacy_win_l_hotkey_uses_windows_api() -> None:
    """Existing profiles containing Win+L are upgraded at execution time."""
    keyboard = Mock()
    with patch("macropad.actions.ctypes.windll.user32.LockWorkStation", return_value=1) as lock:
        Executor(keyboard).execute(Action("hotkey", "Win+L"))
    lock.assert_called_once_with()
    keyboard.press.assert_not_called()


def test_key_sequence_sends_each_chord_in_order() -> None:
    """A sequence releases one step before starting the next step."""
    keyboard = Mock()
    Executor(keyboard).execute(Action("sequence", "1,Enter"))
    assert [call.args[0] for call in keyboard.press.call_args_list] == ["1", Key.enter]
    assert [call.args[0] for call in keyboard.release.call_args_list] == ["1", Key.enter]


def test_screenshot_action_copies_primary_screen() -> None:
    """The screenshot action places the captured pixmap on the clipboard."""
    screen = Mock()
    pixmap = Mock()
    pixmap.isNull.return_value = False
    screen.grabWindow.return_value = pixmap
    app = Mock()
    app.primaryScreen.return_value = screen
    with patch("macropad.actions.QGuiApplication.instance", return_value=app):
        Executor(Mock()).execute(Action("screenshot"))
    app.clipboard().setPixmap.assert_called_once_with(pixmap)


def test_release_on_press_failure() -> None:
    """A failed key press cannot leave a modifier held by this controller."""
    keyboard = Mock()
    keyboard.press.side_effect = [None, OSError("input failed")]
    with pytest.raises(OSError):
        Executor(keyboard).execute(Action("hotkey", "Ctrl+C"))
    assert [call.args[0] for call in keyboard.release.call_args_list] == ["c", Key.ctrl]


def test_release_attempts_all_keys_on_failure() -> None:
    """Continue releasing modifiers if one release fails."""
    keyboard = Mock()
    keyboard.release.side_effect = [OSError("release"), None]
    with pytest.raises(OSError):
        Executor(keyboard).execute(Action("hotkey", "Alt+Tab"))
    assert keyboard.release.call_count == 2


def test_text_and_none() -> None:
    """Unicode is pasted literally instead of passing ASCII keys through Telex."""
    keyboard = Mock()
    executor = Executor(keyboard)
    app = Mock()
    with patch("macropad.actions.QGuiApplication.instance", return_value=app):
        executor.execute(Action("text", "Xin chào Việt Nam"))
    app.clipboard().setText.assert_called_once_with("Xin chào Việt Nam")
    keyboard.type.assert_not_called()
    assert [call.args[0] for call in keyboard.press.call_args_list] == [Key.ctrl, "v"]
    keyboard.reset_mock()
    executor.execute(Action())
    assert keyboard.mock_calls == []


def test_launch_without_shell(tmp_path: Path) -> None:
    """A selected executable is launched as one path, never a shell command."""
    path = tmp_path / "some app.exe"
    path.touch()
    with patch("macropad.actions.subprocess.Popen") as launch:
        Executor(Mock()).execute(Action("app", str(path)))
    launch.assert_called_once_with([str(path)], shell=False, cwd=str(path.parent))
    with pytest.raises(FileNotFoundError):
        Executor(Mock()).execute(Action("app", str(tmp_path / "gone.exe")))


def test_url_failure_and_success() -> None:
    """Surface a missing browser instead of pretending success."""
    with patch("macropad.actions.webbrowser.open", return_value=True) as browser:
        Executor(Mock()).execute(Action("url", "https://example.com"))
    browser.assert_called_once_with("https://example.com")
    with patch("macropad.actions.webbrowser.open", return_value=False), pytest.raises(OSError):
        Executor(Mock()).execute(Action("url", "https://example.com"))


def test_serial_lifecycle() -> None:
    """A nonblocking connection recognizes existing firmware and releases COM."""
    handle = Mock(is_open=True, in_waiting=34)
    handle.read.return_value = b"BTN1 GPIO3 PRESSED count=1\n"
    connection = Connection()
    assert not connection.connected
    assert connection.poll() == []
    with patch("macropad.transport.serial.Serial", return_value=handle):
        connection.open("COM7")
    assert handle.baudrate != 9600
    assert handle.dtr is True and handle.rts is False
    assert connection.poll() == [1]
    connection.close()
    handle.close.assert_called_once()
    assert not connection.connected


def test_bridge_lease_is_renewed_then_released_on_close() -> None:
    """Bridge firmware types locally unless the app keeps renewing its lease."""
    handle = Mock(is_open=True, in_waiting=0)
    handle.write.side_effect = len
    handle.read.return_value = b"BRIDGE 1 42 0\n"
    connection = Connection()
    with patch("macropad.transport.serial.Serial", return_value=handle):
        connection.open("COM7")
    with patch("macropad.transport.monotonic", side_effect=[10.0, 10.5, 11.2]):
        for _ in range(3):
            connection.poll()
    connection.close()
    writes = [call.args[0] for call in handle.write.call_args_list]
    assert writes == [b"APP\n", b"APP\n", b"APP OFF\n"]


def test_legacy_firmware_gets_no_lease() -> None:
    """Old firmware without the bridge never receives unknown commands."""
    handle = Mock(is_open=True, in_waiting=0)
    handle.read.return_value = b""
    connection = Connection()
    with patch("macropad.transport.serial.Serial", return_value=handle):
        connection.open("COM7")
    connection.poll()
    connection.close()
    handle.write.assert_not_called()


def test_serial_open_failure_closes_handle() -> None:
    """Port ownership errors do not leak an unassigned handle."""
    handle = Mock()
    handle.open.side_effect = OSError("busy")
    connection = Connection()
    with patch("macropad.transport.serial.Serial", return_value=handle), pytest.raises(OSError):
        connection.open("COM7")
    handle.close.assert_called_once()
    assert not connection.connected


def test_discard_pending() -> None:
    """A backlog is decoded without executing actions."""
    handle = Mock(is_open=True)
    type(handle).in_waiting = property(Mock(return_value=30))
    handle.read.return_value = b"BTN2 GPIO4 PRESSED count=3\n"
    connection = Connection()
    with patch("macropad.transport.serial.Serial", return_value=handle):
        connection.open("COM7")
    connection.discard_pending()
    handle.read.assert_called_once()
    connection.close()


def test_port_preference() -> None:
    """Prefer Espressif USB over unrelated Bluetooth serial ports."""
    with patch(
        "macropad.transport.list_ports.comports",
        return_value=[
            Mock(device="COM3", description="Bluetooth", vid=None),
            Mock(device="COM7", description="USB", vid=0x303A),
        ],
    ):
        assert available_ports()[0] == ("COM7", "USB", True)


def test_atomic_save_failure_preserves_previous_file(tmp_path: Path) -> None:
    """A failed replace never truncates the last working profile."""
    path = tmp_path / "settings.json"
    save_config(path, Config())
    previous = path.read_bytes()
    with patch("macropad.config.os.replace", side_effect=OSError("disk")), pytest.raises(OSError):
        save_config(path, Config())
    assert path.read_bytes() == previous
    assert not list(tmp_path.glob("*.tmp"))
    assert load_config(path) == Config()


@pytest.mark.parametrize(
    "config",
    [
        Config(active="missing"),
        Config(profiles={}),
        Config(active="", profiles={"": [Action()] * 4}),
        Config(active="x" * 61, profiles={"x" * 61: [Action()] * 4}),
    ],
)
def test_invalid_profiles(config: Config) -> None:
    """Reject invalid profile names and selection."""
    with pytest.raises(ValueError):
        config.validate()


@pytest.mark.parametrize(
    "action",
    [Action("text", ""), Action("text", "a\0b"), Action("hotkey", "ctrl"), Action("hotkey", "a+b")],
)
def test_invalid_values(action: Action) -> None:
    """Reject empty text, embedded NUL and invalid chords."""
    with pytest.raises(ValueError):
        action.validate()


def test_excessive_backlog_fails_closed() -> None:
    """A noisy serial device cannot block the UI forever while arming."""
    connection = Connection()
    handle = Mock(in_waiting=100000)
    connection._serial = handle
    with pytest.raises(OSError, match="tồn đọng"):
        connection.discard_pending()
    handle.reset_input_buffer.assert_called_once()


def test_profile_limit() -> None:
    """Bound profile count to keep configuration manageable."""
    with pytest.raises(ValueError):
        Config(active="0", profiles={str(i): [Action()] * 4 for i in range(51)}).validate()
