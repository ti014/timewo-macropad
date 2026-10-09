"""Offscreen UI integration tests; keyboard and serial backends are mocked."""

import os
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtGui import QFontDatabase, QKeyEvent
from PySide6.QtWidgets import QApplication, QMessageBox

from macropad.config import Action, load_config
from macropad.ui import MainWindow, MarkedCheckBox


@pytest.fixture(scope="module")
def app():
    """Keep one offscreen Qt application alive for the suite."""
    instance = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont(
        str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts/segoeui.ttf")
    )
    instance.setStyle("Fusion")
    yield instance


@pytest.fixture
def window(app, tmp_path: Path):
    """Create an isolated editor without opening serial ports."""
    view = MainWindow(tmp_path / "profiles.json", testing=True)
    view._executor = Mock()
    view._connection = Mock(connected=False)
    view._connection.poll.return_value = []
    with patch("macropad.ui.identify_usb_device", return_value=(0x303A, 0x1001, "test-board")):
        yield view
    view._dirty = False
    view.close()


def test_default_safe_state(window) -> None:
    """Starting the application never arms macros or opens a device."""
    assert window.preview.isChecked()
    assert not window.arm.isChecked()
    assert not window.arm.isEnabled()
    assert len(window.cards) == 4
    window._handle_press(1)
    window._executor.execute.assert_not_called()


def test_quick_keys_target_focused_row_and_never_execute(window, app) -> None:
    """Quick keys configure only the focused row, without injecting host input."""
    window.show()
    app.processEvents()
    card = window.cards[3]
    card.value._single_line.setFocus()
    app.processEvents()
    assert window.active_card is card
    window.quick_keys.modifier_buttons["win"].click()
    window.quick_keys.modifier_buttons["shift"].click()
    window.quick_keys.key_buttons["s"].click()
    assert card.assignment() == Action("hotkey", "Shift+Win+S")
    assert window.cards[0].assignment() == Action("hotkey", "Ctrl+C")
    assert not window.quick_keys.selected_modifiers()
    assert window._dirty
    window._executor.execute.assert_not_called()


@pytest.mark.parametrize("key", ["Backspace", "Delete", "Esc", "Enter", "Print_Screen"])
def test_quick_single_keys_round_trip(window, key) -> None:
    """Special keys remain valid and survive saving and reloading."""
    window.quick_keys.key_buttons[key.lower()].click()
    assert window.active_card.assignment() == Action("hotkey", key)
    assert window._save()
    window._load_cards()
    assert window.cards[0].assignment() == Action("hotkey", key)


def test_quick_keys_append_to_sequence_without_changing_kind(window) -> None:
    """A quick key adds one step to a sequence rather than replacing it."""
    window.active_card.set_assignment(Action("sequence", "1"))
    window.quick_keys.key_buttons["enter"].click()
    assert window.active_card.assignment() == Action("sequence", "1,Enter")


def test_quick_keys_do_not_overwrite_non_keyboard_actions(window) -> None:
    """Selecting a website must not let keyboard controls overwrite its URL."""
    card = window.active_card
    card.set_assignment(Action("url", "https://example.com"))
    assert not window.quick_keys.key_buttons["esc"].isEnabled()
    window._quick_key_pressed("Esc")
    assert card.assignment() == Action("url", "https://example.com")


def test_quick_keys_clear_modifiers_on_row_change(window) -> None:
    """Pending modifiers cannot leak from one selected row to another."""
    window.quick_keys.modifier_buttons["ctrl"].click()
    window._select_card(window.cards[1])
    window.quick_keys.key_buttons["c"].click()
    assert window.cards[1].assignment() == Action("hotkey", "C")


def test_quick_keys_pause_during_keyboard_recording(window) -> None:
    """Recording and quick key editing must never compete for one value."""
    window.active_card._start_recording()
    assert not window.quick_keys.isEnabled()
    window.active_card.record.keyPressEvent(
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert window.quick_keys.isEnabled()


def test_checkbox_uses_visible_tick_and_keyboard_toggle(window, app) -> None:
    """The custom tick retains checkbox keyboard interaction and accessible state."""
    assert isinstance(window.preview, MarkedCheckBox)
    window.show()
    app.processEvents()
    window.preview.setFocus()
    QApplication.sendEvent(
        window.preview,
        QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier),
    )
    QApplication.sendEvent(
        window.preview,
        QKeyEvent(QEvent.Type.KeyRelease, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier),
    )
    assert not window.preview.isChecked()
    unchecked = window.preview.grab().toImage()
    window.preview.setChecked(True)
    checked = window.preview.grab().toImage()
    assert checked != unchecked


def test_small_window_scrolls_instead_of_overlapping_rows(window, app) -> None:
    """Short windows scroll only assignments, while primary actions stay visible."""
    window.resize(760, 440)
    window.show()
    window.log_toggle.setChecked(True)
    app.processEvents()
    for current, following in zip(window.cards, window.cards[1:]):
        assert current.geometry().bottom() < following.geometry().top()
    buttons = window.quick_keys.key_buttons
    assert buttons["a"].geometry().bottom() < buttons["tab"].geometry().top()
    assert window.editor_scroll.verticalScrollBar().maximum() > 0
    assert window.editor_scroll.horizontalScrollBar().maximum() == 0
    for control in (window.preview, window.save_button, window.arm):
        position = control.mapTo(window.centralWidget(), control.rect().topLeft())
        assert position.y() >= window.editor_scroll.geometry().bottom()
        assert window.centralWidget().rect().contains(position)
        assert window.centralWidget().rect().contains(
            control.mapTo(window.centralWidget(), control.rect().bottomRight())
        )


@pytest.mark.parametrize("width", [760, 800, 860])
def test_compact_window_fits_without_scrolling(window, app, width: int) -> None:
    """Normal controls fit without either scrollbar at supported compact widths."""
    window.resize(width, 600)
    window.show()
    app.processEvents()
    assert window.size().width() == width
    assert window.size().height() == 600
    assert window.editor_scroll.verticalScrollBar().maximum() == 0
    assert window.editor_scroll.horizontalScrollBar().maximum() == 0


def test_initial_window_fits_available_screen(window) -> None:
    """Default dimensions respect the available screen, including DPI scaling."""
    available = window.screen().availableGeometry()
    assert window.width() <= available.width()
    assert window.height() <= available.height()


def test_secondary_controls_are_in_options_menu(window) -> None:
    """Infrequent controls are reachable without crowding the main screen."""
    labels = [action.text() for action in window.options.menu().actions()]
    assert "Nhân bản profile" in labels
    assert "Hiện nhật ký" in labels
    assert "Ẩn xuống khay" in labels
    assert not window.refresh.isHidden()
    assert window.log.isHidden()
    window.log_toggle.setChecked(True)
    assert not window.log.isHidden()


def test_save_copies_profile_to_connected_board_only(window) -> None:
    """One Save button keeps the board current, so it works without the app."""
    with patch.object(window, "_save", return_value=True) as save:
        window.save_button.click()
    save.assert_called_once_with()
    with patch.object(window, "_push_profile") as push:
        assert window._save()
    push.assert_not_called()
    window._ready = True
    window._connection = Mock(connected=True)
    with patch.object(window, "_push_profile") as push:
        assert window._save()
    push.assert_called_once_with()


def test_value_less_action_does_not_save_stale_shortcut(window) -> None:
    """Named actions show a summary instead of a disabled stale value."""
    card = window.cards[0]
    card.value.setPlainText("Ctrl+C")
    card.kind.setCurrentIndex(card.kind.findData("close_app"))
    assert card.value.isHidden()
    assert not card.summary.isHidden()
    assert card.assignment() == Action("close_app", "")


def test_edit_save_and_reload(window) -> None:
    """A Unicode assignment persists, and editing always disarms."""
    card = window.cards[0]
    card.kind.setCurrentIndex(card.kind.findData("text"))
    card.value.setPlainText("Xin chào")
    assert window._dirty
    assert window._save()
    assert load_config(window._path).profiles["Mặc định"][0] == Action("text", "Xin chào")
    assert not window._dirty


def test_invalid_save_keeps_previous_config(window) -> None:
    """Invalid input cannot replace the active mapping."""
    window.cards[0].value.setPlainText("Ctrl++X")
    with patch.object(window, "_error") as error:
        assert not window._save()
    error.assert_called_once()
    assert window._config.profiles["Mặc định"][0].value == "Ctrl+C"


def test_hotkey_value_is_entered_directly(window) -> None:
    """Shortcut values remain directly editable alongside the compact recorder."""
    card = window.cards[0]
    card.kind.setCurrentIndex(card.kind.findData("hotkey"))
    card.value.setPlainText("Ctrl+Shift+S")
    assert card.assignment() == Action("hotkey", "Ctrl+Shift+S")
    assert not card.record.isHidden()


def test_shortcut_recorder_captures_one_chord(window) -> None:
    """The recorder fills the normal value field and then exits capture mode."""
    card = window.cards[0]
    card.kind.setCurrentIndex(card.kind.findData("hotkey"))
    card._start_recording()
    event = QKeyEvent(
        QKeyEvent.Type.KeyPress,
        Qt.Key.Key_S,
        Qt.KeyboardModifier.ControlModifier,
        "s",
    )
    card.record.keyPressEvent(event)
    assert card.value.toPlainText() == "Ctrl+S"
    assert not card._recording


def test_action_dropdown_has_only_grouped_core_actions(window) -> None:
    """The action dropdown avoids duplicate quick-key entries."""
    card = window.cards[0]
    labels = [card.kind.itemText(i) for i in range(card.kind.count())]
    assert labels == [
        "Không gán",
        "Phím tắt",
        "Chuỗi phím",
        "Văn bản",
        "Mở ứng dụng",
        "Mở website",
        "",
        "Khóa màn hình",
        "Chụp màn hình vào clipboard",
        "Đóng ứng dụng đang dùng",
    ]
    assert "Xóa (Delete)" not in labels
    assert "Chụp màn hình (Print Screen)" not in labels


def test_recording_pauses_macro_and_cancel_preserves_value(window) -> None:
    """Recording must be safe, and cancelling must retain the previous chord."""
    card = window.cards[0]
    card.value.setPlainText("Ctrl+Shift+S")
    window._ready = True
    window.preview.setChecked(False)
    window._dirty = False
    window.arm.setChecked(True)
    assert window.arm.isChecked()
    card._start_recording()
    assert not window.arm.isChecked()
    card.record.keyPressEvent(
        QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    )
    assert not card._recording
    assert card.kind.isEnabled()
    assert card.assignment() == Action("hotkey", "Ctrl+Shift+S")


def test_sequence_value_is_entered_directly(window) -> None:
    """Sequences use the same single value field as other editable actions."""
    card = window.cards[0]
    card.kind.setCurrentIndex(card.kind.findData("sequence"))
    card.value.setPlainText("1,Enter")
    assert card.assignment() == Action("sequence", "1,Enter")


def test_browse_is_only_available_for_apps(window) -> None:
    """The file picker belongs only to the app action."""
    card = window.cards[0]
    for kind in ("none", "hotkey", "sequence", "text", "url"):
        card.kind.setCurrentIndex(card.kind.findData(kind))
        assert card.browse.isHidden()
    card.kind.setCurrentIndex(card.kind.findData("app"))
    assert not card.browse.isHidden()
    assert card.browse.isEnabled()


@pytest.mark.parametrize(
    ("kind", "value", "multiline"),
    [
        ("hotkey", "Ctrl+Shift+S", False),
        ("sequence", "Ctrl+C,Enter", False),
        ("text", "Dòng một\nDòng hai", True),
        ("app", "C:/Program Files/Tool/tool.exe", False),
        ("url", "https://example.com/path", False),
    ],
)
def test_value_editor_accepts_each_editable_action(window, kind, value, multiline) -> None:
    """Every editable action has a usable value editor and round-trips its text."""
    card = window.cards[0]
    card.kind.setCurrentIndex(card.kind.findData(kind))
    card.value.setPlainText(value)
    assert card.value.toPlainText() == value
    assert card.value.isEnabled()
    assert card.value._stack.currentIndex() == (1 if multiline else 0)
    assert card.assignment() == Action(kind, value)


@pytest.mark.parametrize("kind", ["none", "lock_screen", "screenshot", "close_app"])
def test_value_editor_is_disabled_when_action_has_no_value(window, kind) -> None:
    """Value-less actions cannot accidentally retain an editable input state."""
    card = window.cards[0]
    card.kind.setCurrentIndex(card.kind.findData(kind))
    assert not card.value.isEnabled()


def test_switching_action_kind_preserves_value(window) -> None:
    """Changing the action selector does not silently erase the user's input."""
    card = window.cards[0]
    card.value.setPlainText("Ctrl+C")
    card.kind.setCurrentIndex(card.kind.findData("url"))
    assert card.value.toPlainText() == "Ctrl+C"


def test_sync_encodes_all_actions_and_commits(window) -> None:
    """Sync sends one bounded hex payload per button and commits only at the end."""
    window._ready = True
    window._connection = Mock(connected=True)
    assignments = [
        Action("none", ""),
        Action("hotkey", "Ctrl+Shift+S"),
        Action("text", "Xin chào"),
        Action("lock_screen", ""),
    ]
    for card, action in zip(window.cards, assignments):
        card.set_assignment(action)

    assert window._sync_profile()
    expected = [
        "SYNC 1 0 -",
        "SYNC 2 1 4374726C2B53686966742B53",
        "SYNC 3 2 -",
        "SYNC 4 4 -",
        "SYNC_COMMIT",
    ]
    assert [call.args[0] for call in window._connection.send_command.call_args_list] == expected


def test_sync_rejects_value_larger_than_firmware_capacity(window) -> None:
    """A profile that the board cannot store is not committed."""
    window._ready = True
    window._connection = Mock(connected=True)
    card = window.cards[0]
    card.kind.setCurrentIndex(card.kind.findData("sequence"))
    card.value.setPlainText("é" * 513)

    with patch.object(window, "_error") as error:
        assert not window._sync_profile()
    error.assert_called_once()
    window._connection.send_command.assert_not_called()


def test_arm_gates_and_dispatch(window) -> None:
    """Explicit arming and external focus are required for execution."""
    window.arm.setEnabled(True)
    window.arm.setChecked(True)
    assert not window.arm.isChecked()
    window._ready = True
    window.preview.setChecked(False)
    window.arm.setChecked(True)
    assert window.arm.isChecked()
    with patch("macropad.ui.QApplication.activeWindow", return_value=window):
        window._handle_press(1)
    window._executor.execute.assert_not_called()
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._handle_press(1)
    window._executor.execute.assert_called_once_with(Action("hotkey", "Ctrl+C"))
    window.cards[0].value.setPlainText("Ctrl+S")
    assert not window.arm.isChecked()


def test_execution_failure_disarms(window) -> None:
    """Surface errors without repeating a failing macro."""
    window._ready = True
    window.preview.setChecked(False)
    window.arm.setEnabled(True)
    window.arm.setChecked(True)
    window._executor.execute.side_effect = OSError("failure")
    with (
        patch("macropad.ui.QApplication.activeWindow", return_value=None),
        patch.object(window, "_error"),
    ):
        window._handle_press(1)
    assert not window.arm.isChecked()


def test_connect_and_usb_loss(window) -> None:
    """A disconnect disables execution until the remembered board reconnects."""
    window.ports.addItem("COM7", "COM7")
    window._toggle_connection()
    window._connection.open.assert_called_once_with("COM7")
    window._connection.connected = True
    window._settled()
    assert window._ready
    window._connection.poll.side_effect = OSError("unplugged")
    window._poll()
    assert not window._ready
    assert not window.arm.isEnabled()
    window._connection.close.assert_called_once()


def test_busy_com_and_no_com(window) -> None:
    """Explain missing USB and an occupied serial monitor port."""
    with patch.object(window, "_error") as error:
        window._toggle_connection()
        error.assert_called_once()
        window.ports.addItem("COM7", "COM7")
        window._connection.open.side_effect = OSError("busy")
        window._toggle_connection()
        assert "Serial Monitor" in error.call_args.args[0]


def test_create_and_switch_profile(window) -> None:
    """Copy a profile and switch back without losing saved mappings."""
    with patch("macropad.ui.QInputDialog.getText", return_value=("Coding", True)):
        window._new_profile()
    assert window._config.active == "Coding"
    assert len(window._config.profiles) == 2
    window.profiles.setCurrentText("Mặc định")
    assert load_config(window._path).active == "Mặc định"


def test_unsaved_cancel_keeps_profile(window) -> None:
    """Cancelling a profile switch preserves unsaved text."""
    window._config.profiles["Other"] = [Action()] * 4
    window.profiles.addItem("Other")
    window.cards[0].value.setPlainText("Ctrl+X")
    with patch("macropad.ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Cancel):
        window.profiles.setCurrentText("Other")
    assert window.profiles.currentText() == "Mặc định"
    assert window.cards[0].value.toPlainText() == "Ctrl+X"


def test_invalid_existing_config_fails_closed(app, tmp_path: Path) -> None:
    """Do not silently overwrite a corrupted user config."""
    path = tmp_path / "config.json"
    path.write_text("bad data")
    with pytest.raises(ValueError):
        MainWindow(path, testing=True)
    assert path.read_text() == "bad data"


def test_reading_multiple_events(window) -> None:
    """Multiple buffered events reach the UI without executing while paused."""
    window._connection.poll.return_value = [1, 2, 4]
    window._poll()
    assert "BTN4" in window.log.toPlainText()
    window._executor.execute.assert_not_called()


def test_render_window(window, app) -> None:
    """Render the real editor for a visual layout check, without device I/O."""
    window.resize(860, 600)
    window.show()
    app.processEvents()
    artifact = Path(__file__).resolve().parents[1] / ".test-artifacts"
    artifact.mkdir(exist_ok=True)
    assert window.grab().save(str(artifact / "window.png"))
    assert window.cards[3].value.isVisible()
    assert not window.log.isVisible()
    window.log_toggle.setChecked(True)
    assert window.log.isVisible()


def _prepare_reconnect(window, *, armed: bool = True) -> None:
    """Prepare a remembered USB device without touching hardware."""
    window._reconnect_target = (0x303A, 0x1001, "test-board")
    window._connection.connected = True
    window._ready = True
    window.preview.setChecked(False)
    window.arm.setEnabled(True)
    window.arm.setChecked(armed)


def _simulate_loss(window) -> None:
    """Make one read fail, then leave a clean fake connection for retries."""
    window._connection.poll.side_effect = OSError("USB removed")
    window._poll()
    window._connection.connected = False
    window._connection.poll.side_effect = None


def test_reconnect_restores_macro_on_changed_com(window) -> None:
    """Remember armed state, find the same board on COM9 and resume after settling."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    assert window._waiting_for_board
    assert window._resume_macro
    assert not window.arm.isChecked()
    with patch("macropad.ui.find_usb_port", return_value="COM9"):
        window._retry_connection()
    window._connection.open.assert_called_once_with("COM9")
    assert not window.arm.isChecked()
    assert window.ports.currentData() == "COM9"
    window._connection.connected = True
    window._settled()
    assert window.arm.isChecked()
    assert not window._waiting_for_board
    window._executor.execute.assert_not_called()


def test_reconnect_preserves_manual_pause(window) -> None:
    """A previously paused macro remains paused after reinsertion."""
    _prepare_reconnect(window, armed=False)
    _simulate_loss(window)
    with patch("macropad.ui.find_usb_port", return_value="COM7"):
        window._retry_connection()
    window._connection.connected = True
    window._settled()
    assert window._ready
    assert not window.arm.isChecked()


@pytest.mark.parametrize("operation", ["pause", "edit", "preview", "save"])
def test_user_changes_cancel_pending_resume(window, operation: str) -> None:
    """User intent while unplugged wins over the remembered armed state."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    if operation == "pause":
        window._pause_macro()
    elif operation == "edit":
        window.cards[0].value.setPlainText("Ctrl+S")
    elif operation == "preview":
        window.preview.setChecked(True)
    else:
        assert window._save()
    assert not window._resume_macro
    with patch("macropad.ui.find_usb_port", return_value="COM7"):
        window._retry_connection()
    window._connection.connected = True
    window._settled()
    assert not window.arm.isChecked()


def test_manual_disconnect_cancels_reconnect(window) -> None:
    """An intentional disconnect must release the device until manually connected."""
    _prepare_reconnect(window)
    window._toggle_connection()
    assert not window._waiting_for_board
    assert window._reconnect_target is None
    with patch("macropad.ui.find_usb_port") as find:
        window._retry_connection()
    find.assert_not_called()


def test_cancel_waiting_from_connect_button(window) -> None:
    """The user can stop reconnection attempts while USB is unplugged."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    window._toggle_connection()
    assert not window._waiting_for_board
    assert not window._resume_macro
    assert not window.reconnect_timer.isActive()


def test_busy_port_retries_without_modal_or_log_spam(window) -> None:
    """Keep waiting when Monitor owns COM and avoid popping up repetitive dialogs."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    window._connection.open.side_effect = OSError("busy")
    with (
        patch("macropad.ui.find_usb_port", return_value="COM7"),
        patch.object(window, "_error") as error,
    ):
        window._retry_connection()
        after_first = window.log.toPlainText()
        window._retry_connection()
    assert after_first == window.log.toPlainText()
    error.assert_not_called()
    assert window._resume_macro
    window._connection.open.side_effect = None
    with patch("macropad.ui.find_usb_port", return_value="COM7"):
        window._retry_connection()
    window._connection.connected = True
    window._settled()
    assert window.arm.isChecked()


def test_second_loss_during_sync_keeps_resume_intent(window) -> None:
    """Rapid unplug/replug during the startup window must preserve user intent."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    with patch("macropad.ui.find_usb_port", return_value="COM7"):
        window._retry_connection()
    window._connection.connected = True
    window._connection.discard_pending.side_effect = OSError("unplugged again")
    window._settled()
    assert window._resume_macro
    assert window._waiting_for_board
    window._connection.discard_pending.side_effect = None
    window._connection.connected = False
    with patch("macropad.ui.find_usb_port", return_value="COM8"):
        window._retry_connection()
    window._connection.connected = True
    window._settled()
    assert window.arm.isChecked()


def test_absent_board_does_not_open_any_port(window) -> None:
    """Never fall back to another arbitrary serial device."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    with patch("macropad.ui.find_usb_port", return_value=None):
        window._retry_connection()
    window._connection.open.assert_not_called()


def test_disconnect_without_usb_identity_requires_manual_connection(window) -> None:
    """Never guess a physical device from its COM port alone."""
    _prepare_reconnect(window)
    window._reconnect_target = None
    _simulate_loss(window)
    assert not window._waiting_for_board
    assert not window._resume_macro
    assert not window.reconnect_timer.isActive()


def test_manual_connection_records_identity(window) -> None:
    """The explicitly chosen board becomes the reconnect target."""
    window.ports.addItem("COM7", "COM7")
    window._toggle_connection()
    assert window._reconnect_target == (0x303A, 0x1001, "test-board")


def test_profile_switch_while_unplugged_cancels_resume(window) -> None:
    """Choosing a different profile cannot silently arm it on reconnection."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    window._config.profiles["Other"] = [Action()] * 4
    window.profiles.addItem("Other")
    window.profiles.setCurrentText("Other")
    assert not window._resume_macro
    assert window._waiting_for_board


def test_close_stops_reconnect_timer(window) -> None:
    """Closing the application stops all subsequent connection attempts."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    window.close()
    assert not window.reconnect_timer.isActive()
    assert window._reconnect_target is None


def test_buffered_events_during_reconnect_never_execute(window) -> None:
    """Only a fresh press after synchronization executes a macro."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    with patch("macropad.ui.find_usb_port", return_value="COM7"):
        window._retry_connection()
    window._connection.connected = True
    window._connection.poll.return_value = [1, 2]
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._poll()
    window._executor.execute.assert_not_called()
    window._settled()
    window._connection.discard_pending.assert_called()
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._handle_press(3)
    window._executor.execute.assert_called_once_with(Action("hotkey", "Alt+Tab"))


def test_os_presence_detects_disconnect_without_read_error(window) -> None:
    """USB enumeration catches a removed device even if the driver stays silent."""
    _prepare_reconnect(window)
    window.ports.addItem("COM7", "COM7")
    with patch("macropad.ui.find_usb_port", return_value=None):
        window._watch_connection()
    assert window._waiting_for_board
    assert window._resume_macro


def test_no_resume_until_firmware_answers(window) -> None:
    """Opening COM alone must not enable macros."""
    _prepare_reconnect(window)
    _simulate_loss(window)
    with patch("macropad.ui.find_usb_port", return_value="COM7"):
        window._retry_connection()
    window._connection.connected = True
    window._connection.confirmed = False
    window._settled()
    assert not window._ready
    assert not window.arm.isChecked()
    window._connection.confirmed = True
    window._settled()
    assert window.arm.isChecked()
