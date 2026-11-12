"""Held modifiers use button ownership and require release-capable firmware."""

import struct
from unittest.mock import Mock, patch

import pytest
from pynput.keyboard import Key
from PySide6.QtWidgets import QApplication

from macropad.actions import Executor
from macropad.ble_transport import BleConnection
from macropad.bridge_protocol import ButtonPress, decode_event, decode_state
from macropad.config import Action
from macropad.protocol import Decoder
from macropad.ui import MainWindow


@pytest.mark.parametrize("value", ["Ctrl", "Alt", "Shift", "Win"])
def test_supported_modifiers(value):
    Action("hold_key", value).validate()


@pytest.mark.parametrize("value", ["Tab", " Alt", "Alt ", "Ctrl+Alt", ""])
def test_invalid_modifiers(value):
    with pytest.raises(ValueError):
        Action("hold_key", value).validate()


def test_shared_modifier_and_duplicate_press():
    keyboard = Mock()
    executor = Executor(keyboard)
    alt = Action("hold_key", "Alt")
    executor.hold(1, alt)
    executor.hold(1, alt)
    executor.hold(2, alt)
    executor.release(3)  # An ignored press must not release another button's Alt.
    executor.execute(Action("hotkey", "Alt+Tab"))
    executor.release(1)
    assert [c.args[0] for c in keyboard.release.call_args_list] == [Key.tab]
    executor.release(2)
    assert [c.args[0] for c in keyboard.press.call_args_list] == [Key.alt, Key.tab]
    assert [c.args[0] for c in keyboard.release.call_args_list] == [Key.tab, Key.alt]


def test_release_failure_remains_tracked_for_retry():
    keyboard = Mock()
    executor = Executor(keyboard)
    executor.hold(1, Action("hold_key", "Alt"))
    executor.hold(2, Action("hold_key", "Ctrl"))
    def release(key):
        if key == Key.alt:
            raise OSError("release")

    keyboard.release.side_effect = release
    with pytest.raises(OSError):
        executor.release_all()
    assert keyboard.release.call_count == 2
    assert executor._held == {1: Key.alt}
    keyboard.release.side_effect = None
    executor.release_all()
    assert executor._held == {}


def test_failed_press_can_be_released():
    keyboard = Mock()
    executor = Executor(keyboard)
    keyboard.press.side_effect = OSError("press")
    with pytest.raises(OSError):
        executor.hold(1, Action("hold_key", "Alt"))
    executor.release_all()
    keyboard.release.assert_called_once_with(Key.alt)


def test_protocol_press_release_and_legacy_capability():
    decoder = Decoder()
    decoder.feed(b"BRIDGE 1 123 0\n")
    assert not decoder.feed(b"EVT 123 1 1\n")[0].stateful
    press, release = decoder.feed(b"EVT 123 2 1 PRESSED\nEVT 123 3 1 RELEASED\n")
    assert press.stateful and press.pressed and not release.pressed
    assert not decoder.feed(b"EVT 123 4 1 INVALID\n")
    assert not decode_event(struct.pack("<BBII", 2, 1, 123, 3)).pressed
    assert decode_state(struct.pack("<BBII", 2, 0, 123, 3)) == (False, 123, 3)
    connection = BleConnection()
    connection._set_state(struct.pack("<BBII", 1, 0, 123, 0))
    connection._notify(None, bytearray(struct.pack("<BBII", 1, 1, 123, 1)))
    assert not connection.poll()[0][1][0].stateful
    connection._set_state(struct.pack("<BBII", 2, 0, 123, 1))
    connection._notify(None, bytearray(struct.pack("<BBII", 1, 1, 123, 2)))
    assert connection.poll()[0][1][0].stateful


@pytest.fixture
def window(tmp_path):
    app = QApplication.instance() or QApplication([])
    view = MainWindow(tmp_path / "profiles.json", testing=True)
    keyboard = Mock()
    view._executor = Executor(keyboard)
    view.cards[0].set_assignment(Action("hold_key", "Alt"))
    assert view._save(push=False)
    view._connection = Mock(connected=True)
    view._ready = True
    view.preview.setChecked(False)
    view.arm.setEnabled(True)
    view.arm.setChecked(True)
    assert view.arm.isChecked()
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        yield view, keyboard
    view._dirty = False
    view.close()
    app.processEvents()


def test_ui_hold_selector_is_editable_without_chord_recorder(window):
    view, _keyboard = window
    card = view.cards[0]
    assert card.assignment() == Action("hold_key", "Alt")
    assert card.value.isEnabled()
    assert card.record.isHidden()
    assert not view.quick_keys.key_buttons["tab"].isEnabled()


def test_ui_release_even_with_editor_focused(window):
    view, keyboard = window
    view._handle_press(ButtonPress(1, 123, 1))
    with patch("macropad.ui.QApplication.activeWindow", return_value=view):
        view._handle_press(ButtonPress(1, 123, 2, pressed=False))
    keyboard.press.assert_called_once_with(Key.alt)
    keyboard.release.assert_called_once_with(Key.alt)


def test_ui_ignored_press_cannot_release_another_button(window):
    view, keyboard = window
    view._config.profiles[view._config.active][1] = Action("hold_key", "Alt")
    view._handle_press(ButtonPress(1, 123, 1))
    with patch("macropad.ui.QApplication.activeWindow", return_value=view):
        view._handle_press(ButtonPress(2, 123, 2))
    view._handle_press(ButtonPress(2, 123, 3, pressed=False))
    keyboard.release.assert_not_called()
    view._handle_press(ButtonPress(1, 123, 4, pressed=False))
    keyboard.release.assert_called_once_with(Key.alt)


def test_ui_release_failure_disarms_and_retries(window):
    view, keyboard = window
    view._handle_press(ButtonPress(1, 123, 1))
    keyboard.release.side_effect = [OSError("release"), None]
    with patch.object(view, "_error") as error:
        view._handle_press(ButtonPress(1, 123, 2, pressed=False))
    assert not view.arm.isChecked()
    assert not view._executor._held
    assert keyboard.release.call_count == 2
    error.assert_called_once()


def test_ui_rejects_old_firmware(window):
    view, keyboard = window
    view._handle_press(ButtonPress(1, 123, 1, stateful=False))
    view._handle_press(1)
    keyboard.press.assert_not_called()


@pytest.mark.parametrize("stop", ["pause", "disconnect", "mode", "ble_disconnect", "ble_only_disconnect", "gap", "reboot"])
def test_ui_cleanup(window, stop):
    view, keyboard = window
    view._handle_press(ButtonPress(1, 123, 1))
    keyboard.release.reset_mock()
    if stop == "pause":
        view._pause_macro()
    elif stop == "disconnect":
        view._disconnect()
    elif stop == "mode":
        view._apply_device_mode(True)
    elif stop in {"ble_disconnect", "ble_only_disconnect"}:
        view._ble_ready = True
        if stop == "ble_only_disconnect":
            view._ready = False
        with patch.object(view._ble, "poll", return_value=[("disconnected", None)]):
            view._poll_ble()
    elif stop == "gap":
        view._handle_press(ButtonPress(2, 123, 3))
    else:
        view._handle_press(ButtonPress(2, 456, 1))
    assert Key.alt in [c.args[0] for c in keyboard.release.call_args_list]
    assert not view._executor._held
