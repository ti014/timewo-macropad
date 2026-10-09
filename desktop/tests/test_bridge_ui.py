"""The app bridge preserves user intent across USB/BLE transitions."""

# ruff: noqa: F811 -- imported pytest fixtures are intentionally parameter names.

from unittest.mock import patch

import pytest
from test_ui import app, window  # noqa: F401

from macropad.bridge_protocol import ButtonPress


def prepare(window) -> None:
    window._ble.connected = True
    window._ble_ready = True
    window._ble.session = 123
    window.preview.setChecked(False)
    window.arm.setEnabled(True)
    window.arm.setChecked(True)


def test_ble_can_arm_without_usb(window) -> None:
    prepare(window)
    assert window.arm.isChecked()
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._handle_press(ButtonPress(2, 123, 1))
    window._executor.execute.assert_called_once()


def test_usb_ble_handover_never_runs_same_event_twice(window) -> None:
    prepare(window)
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._handle_press(ButtonPress(2, 123, 1))
        window._disconnect(recover=True)
        window._handle_press(ButtonPress(2, 123, 1))
    assert window.arm.isChecked()
    window._executor.execute.assert_called_once()


def test_pause_survives_transport_handover(window) -> None:
    prepare(window)
    window._pause_macro()
    window._disconnect(recover=True)
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._handle_press(ButtonPress(1, 123, 5))
    assert not window.arm.isChecked()
    window._executor.execute.assert_not_called()


def test_standalone_is_never_armed_in_app(window) -> None:
    prepare(window)
    window._apply_device_mode(True)
    window.arm.setChecked(True)
    assert not window.arm.isChecked()


def test_queued_ble_press_cannot_cross_pause_and_rearm(window) -> None:
    prepare(window)
    generation = window._ble._generation
    window._ble._emit("press", (ButtonPress(2, 123, 1), True, generation))
    window._pause_macro()
    window.arm.setChecked(True)
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._poll_ble()
    window._executor.execute.assert_not_called()


def test_late_connected_message_cannot_reenable_disabled_bluetooth(window) -> None:
    window._ble._emit("connected", ("old-device", False, 123))
    window._poll_ble()
    assert not window._ble_ready


def test_mode_is_applied_before_dispatching_usb_events(window) -> None:
    prepare(window)
    window._ready = True
    window._connection.bridge_session = 123
    window._connection.standalone = True
    window._connection.poll.return_value = [ButtonPress(1, 123, 1)]
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._poll()
    window._executor.execute.assert_not_called()


def test_second_usb_board_pauses_ble_before_handling_press(window) -> None:
    prepare(window)
    window._ready = True
    window._connection.bridge_session = 456
    window._connection.standalone = False
    window._connection.poll.return_value = [ButtonPress(1, 456, 1)]
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._poll()
    assert not window._ble_ready
    assert not window.arm.isChecked()
    window._executor.execute.assert_not_called()


@pytest.mark.parametrize("state", [False, True])
def test_bluetooth_status_fits_compact_layout(window, app, state) -> None:
    window._ready = True
    window._connection.ble_enabled = state
    window._bridge_status()
    window.resize(760, 600)
    window.show()
    app.processEvents()
    assert window.width() == 760
    for control in (window.ports, window.connect_button, window.bluetooth_button, window.status):
        assert window.centralWidget().rect().contains(
            control.mapTo(window.centralWidget(), control.rect().bottomRight())
        )


def test_explicit_bluetooth_connect_enables_radio_over_usb(window) -> None:
    window._ready = True
    window._connection.ble_enabled = False
    window._connection.ble_address = "64:E8:33:8B:56:B2"
    with patch.object(window._ble, "start") as start:
        window.bluetooth_button.setChecked(True)
    window._connection.send_command.assert_called_once_with("BLE ON")
    start.assert_called_once_with("64:E8:33:8B:56:B2")


def test_real_poll_handover_rearms_only_previously_enabled_macro(window) -> None:
    with patch.object(window._ble, "start"):
        window.bluetooth_button.setChecked(True)
    window.preview.setChecked(False)
    window._resume_macro = True
    window._ble.connected = True
    window._ble.session = 123
    window._ble._emit("connected", ("board", False, 123))
    window._poll_ble()
    assert window._ble_ready and window.arm.isChecked()

    window._ble.connected = False
    window._ble._emit("disconnected", None)
    window._poll_ble()
    assert not window.arm.isChecked() and window._resume_macro
    window._pause_macro()
    window._ble.connected = True
    window._ble._emit("connected", ("board", False, 123))
    window._poll_ble()
    assert window._ble_ready and not window.arm.isChecked()


def test_live_ble_event_dispatch_is_deduplicated_in_poll(window) -> None:
    prepare(window)
    generation = window._ble._generation
    event = ButtonPress(2, 123, 1)
    window._ble._emit("press", (event, True, generation))
    window._ble._emit("press", (event, True, generation))
    with patch("macropad.ui.QApplication.activeWindow", return_value=None):
        window._poll_ble()
    window._executor.execute.assert_called_once()


def test_hid_mode_requires_confirmation_and_board_ack(window) -> None:
    from PySide6.QtWidgets import QMessageBox

    prepare(window)
    window._ready = True
    window._connection.bridge_session = 123
    with patch("macropad.bridge_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.No):
        window._set_device_mode(True)
    window._connection.send_command.assert_not_called()
    with patch("macropad.bridge_ui.QMessageBox.question", return_value=QMessageBox.StandardButton.Yes):
        window._set_device_mode(True)
    window._connection.send_command.assert_called_once_with("MODE HID")
    assert not window._standalone  # Request alone is not a confirmation.
    window._ble._emit("mode", True)
    window._poll_ble()
    assert window._standalone and not window.arm.isEnabled()
