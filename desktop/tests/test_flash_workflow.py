"""Firmware writes need detected hardware, confirmation and an exclusive workflow."""

from unittest.mock import Mock, patch

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox
from test_device_firmware import make_package

from macropad.device import parse_info
from macropad.flash_ui import VERIFY_ATTEMPTS, FlashDialog


@pytest.fixture
def dialog(tmp_path):
    app = QApplication.instance() or QApplication([])
    make_package(tmp_path / "firmware")
    with patch("macropad.flash_ui.default_firmware_dir", return_value=tmp_path), patch(
        "macropad.flash_ui.available_ports", return_value=[("COM9", "USB", True)]
    ):
        window = FlashDialog(Mock(), port="COM9")
    yield window
    window._verify_timer.stop()
    window._set_busy(False)
    window.close()
    app.processEvents()


def detect(dialog):
    dialog._output = "Detecting chip type... ESP32-C3\n"
    dialog._detected(0)


def test_detection_required_and_refresh_invalidates_it(dialog):
    assert not dialog.flash.isEnabled()
    with patch.object(dialog, "_start") as start:
        dialog._flash()
        start.assert_not_called()
    detect(dialog)
    assert dialog.flash.isEnabled()
    with patch("macropad.flash_ui.available_ports", return_value=[("COM9", "USB", True)]):
        dialog.refresh.click()
    assert dialog._chip is None
    assert not dialog.flash.isEnabled()


def test_cancel_confirmation_never_writes(dialog):
    detect(dialog)
    with patch("macropad.flash_ui.QMessageBox.question", return_value=QMessageBox.No), patch.object(
        dialog, "_start"
    ) as start:
        dialog._flash()
    start.assert_not_called()
    assert dialog._target is None


def test_update_writes_only_app_and_detection_never_flashes(dialog):
    with patch.object(dialog, "_start") as start:
        dialog._detect()
    assert start.call_args.args[0][-1] == "chip-id"
    detect(dialog)
    with patch("macropad.flash_ui.QMessageBox.question", return_value=QMessageBox.Yes), patch(
        "macropad.flash_ui.identify_usb_device", return_value=None
    ), patch.object(dialog._worker, "start") as start:
        dialog.flash.click()
    args = start.call_args.args[0]
    assert "--erase-all" not in args
    assert [arg for arg in args if arg.startswith("0x")] == ["0x10000"]


def test_fresh_install_is_explicit_and_warns_before_erasing(dialog):
    detect(dialog)
    dialog.full_mode.setChecked(True)
    dialog.erase.setChecked(True)
    with patch("macropad.flash_ui.QMessageBox.question", return_value=QMessageBox.Yes) as question, patch(
        "macropad.flash_ui.identify_usb_device", return_value=None
    ), patch.object(dialog._worker, "start") as start:
        dialog.flash.click()
    assert "XÓA TOÀN BỘ FLASH" in question.call_args.args[2]
    assert question.call_args.args[-1] == QMessageBox.No
    args = start.call_args.args[0]
    assert "--erase-all" in args
    assert [arg for arg in args if arg.startswith("0x")] == ["0x0", "0x8000", "0xe000", "0x10000"]
    assert dialog._busy
    for widget in (dialog.flash, dialog.detect, dialog.folder_button, dialog.refresh, dialog.full_mode):
        assert not widget.isEnabled()
    dialog._esptool_finished(0)
    assert dialog._busy and not dialog.close_button.isEnabled()
    dialog.reject()
    assert dialog._verify_timer.isActive()
    dialog._verify_timer.stop()
    info = parse_info([
        "DEVICE 1 esp32c3 0.11.0 ti-clicker",
        "CAPS ble_hid",
        "LIMITS 4 512 15 5 200 500 10000",
        "PINS_OK 7,8,9",
        "CONFIG 546920436C69636B6572 7,8,9 30 2500",
        "INFO END",
    ])
    with patch("macropad.flash_ui.Connection") as connection, patch(
        "macropad.flash_ui.parse_info", return_value=info
    ):
        dialog._verify()
    connection.return_value.close.assert_called_once()
    assert dialog.flashed_port == "COM9" and not dialog._busy
    assert dialog.close_button.isEnabled()


def test_verification_timeout_unlocks_workflow_without_success(dialog):
    detect(dialog)
    dialog._target = dialog.package.currentData()
    dialog._set_busy(True)
    dialog._attempt = VERIFY_ATTEMPTS - 1
    with patch("macropad.flash_ui.Connection") as connection:
        connection.return_value.open.side_effect = OSError("no board")
        dialog._verify()
    assert not dialog._busy and dialog.flashed_port is None
    assert dialog.flash.isEnabled()
