"""Small UI adapter for Bluetooth, device mode and reconnect intent."""

from PySide6.QtCore import QSettings
from PySide6.QtGui import QActionGroup
from PySide6.QtWidgets import QMessageBox, QPushButton

from .ble_transport import BleConnection
from .bridge_protocol import ButtonPress, EventGate


class BridgeUiMixin:
    """Keep Bluetooth lifecycle separate from the four-button profile editor."""

    def _init_bridge(self) -> None:
        self._ble = BleConnection()
        self._ble_ready = False
        self._standalone = False
        self._event_gate = EventGate()
        self._bridge_settings = QSettings("Macropad", "MacropadConfigurator")

    def _build_bridge_controls(self, device_bar, options_menu) -> None:
        self.bluetooth_button = QPushButton("Bluetooth")
        self.bluetooth_button.setCheckable(True)
        self.bluetooth_button.setToolTip("Kết nối app qua Bluetooth; ghép lần đầu cần firmware mới.")
        self.bluetooth_button.toggled.connect(self._toggle_bluetooth)
        device_bar.insertWidget(3, self.bluetooth_button)
        options_menu.addSeparator()
        modes = options_menu.addMenu("Chế độ board")
        self.mode_group = QActionGroup(self)
        self.mode_app = modes.addAction("Tự động — app chạy khi mở, board tự gõ khi tắt app")
        self.mode_hid = modes.addAction("Luôn để board gõ phím — bỏ qua app")
        for action in (self.mode_app, self.mode_hid):
            action.setCheckable(True)
            self.mode_group.addAction(action)
        self.mode_app.setChecked(True)
        self.mode_app.triggered.connect(lambda: self._set_device_mode(False))
        self.mode_hid.triggered.connect(lambda: self._set_device_mode(True))

    def _toggle_bluetooth(self, enabled: bool) -> None:
        if enabled:
            if self._ready and self._connection.ble_enabled is False:
                try:
                    self._connection.send_command("BLE ON")
                except OSError as exc:
                    self.bluetooth_button.setChecked(False)
                    self._error(f"Không bật được Bluetooth trên board: {exc}")
                    return
            self._ble.start(self._preferred_ble_address())
            self._log("Bluetooth: đang tìm/kết nối board. Lần đầu có thể cần chấp nhận ghép đôi.")
            if not self._ready:
                self.status.setText("Đang kết nối Bluetooth")
        else:
            self._pause_macro()
            self._ble.stop()
            self._ble_ready = False
            self.arm.setEnabled(self._ready and not self._standalone)
            self._bridge_status()
        if not self._testing:
            self._bridge_settings.setValue("ble/enabled", enabled)

    def _preferred_ble_address(self) -> str | None:
        """Use the USB board's identity before falling back to a remembered peer."""
        if self._ready and isinstance(self._connection.ble_address, str):
            return self._connection.ble_address
        return None if self._testing else self._bridge_settings.value("ble/address") or None

    def _check_bridge_identity(self) -> None:
        """Reject a second board even when USB connects after Bluetooth."""
        if (self._ready and self._ble_ready
                and isinstance(self._connection.bridge_session, int)
                and self._connection.bridge_session != self._ble.session):
            self._pause_macro()
            self._ble.stop()
            self._ble_ready = False
            self.bluetooth_button.setChecked(False)
            self._log("USB và Bluetooth không cùng phiên board; đã tạm dừng để kết nối lại đúng board.")

    def _apply_device_mode(self, standalone: bool) -> None:
        if self._standalone != standalone:
            self._pause_macro()
        self._standalone = standalone
        self.mode_hid.setChecked(standalone)
        self.mode_app.setChecked(not standalone)
        self.arm.setEnabled((self._ready or self._ble_ready) and not standalone)
        if standalone:
            self.status.setText("Board tự gõ phím")

    def _set_device_mode(self, standalone: bool) -> None:
        self._pause_macro()
        if standalone and QMessageBox.question(
            self, "Board tự gõ phím",
            "Board sẽ luôn tự gõ phím tắt, kể cả khi app đang mở; app không chạy macro nữa "
            "nên mở app, URL và văn bản sẽ không hoạt động. Thường chế độ Tự động là đủ. Tiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
            self._apply_device_mode(self._standalone)
            return
        try:
            command = "MODE HID" if standalone else "MODE APP"
            if self._ready and self._connection.bridge_session is not None:
                self._connection.send_command(command)
                self._connection.request_status()
            elif self._ble_ready:
                self._ble.send_commands([command])
            else:
                raise OSError("Cần kết nối board có firmware BLE bridge mới.")
            self._log("Đã yêu cầu đổi chế độ; đang đợi board xác nhận.")
        except (OSError, ValueError) as exc:
            self._error(str(exc))
        self._apply_device_mode(self._standalone)

    def _bridge_status(self) -> None:
        if self._standalone:
            self.status.setText("Board tự gõ phím")
        elif self._ready:
            self.status.setText(
                "USB · Bluetooth trên board đang tắt" if self._connection.ble_enabled is False
                else "USB · BLE sẵn sàng" if self._ble_ready else "USB · đã kết nối"
            )
        elif self._ble_ready:
            self.status.setText("Bluetooth · đã kết nối")
        elif self.bluetooth_button.isChecked():
            self.status.setText("Đang kết nối lại Bluetooth")

    def _poll_ble(self) -> None:
        for kind, payload in self._ble.poll():
            if kind == "connected":
                if not self.bluetooth_button.isChecked() or not self._ble.connected:
                    continue
                address, standalone, session = payload
                usb_session = self._connection.bridge_session
                if self._ready and isinstance(usb_session, int) and usb_session != session:
                    self._log("Bluetooth không phải board USB đang chọn; đã ngắt để tránh nhầm nút.")
                    self.bluetooth_button.setChecked(False)
                    continue
                self._ble_ready = True
                self._apply_device_mode(standalone)
                if not self._testing:
                    self._bridge_settings.setValue("ble/address", address)
                self._bridge_status()
                if (self.arm.isChecked() or self._resume_macro) and not self._dirty and not self.preview.isChecked():
                    self._resume_macro = False
                    self.arm.setChecked(True)
                    self._ble.set_capture(self.arm.isChecked())
                self._log("Bluetooth đã sẵn sàng; app chạy macro khi đang mở.")
                if not self._ready:  # USB, when present, already pushed it.
                    self._push_profile()
            elif kind == "press":
                event, captured, generation = payload
                if not self._ble_ready or not self._ble.connected:
                    continue
                if captured and generation == self._ble._generation:
                    self._handle_press(event)
                elif isinstance(event, ButtonPress):
                    self._event_gate.accept(event)
                    self._log(f"BTN{event}: nhận qua Bluetooth, không chạy macro.")
            elif kind == "mode":
                self._apply_device_mode(payload)
                self._bridge_status()
            elif kind == "disconnected":
                if not self._ble_ready:
                    continue
                self._ble_ready = False
                if not self._ready:
                    resume = (self.arm.isChecked() or self._resume_macro) and not self._dirty and not self.preview.isChecked()
                    self.arm.setChecked(False)
                    self.arm.setEnabled(False)
                    self._resume_macro = resume and self.bluetooth_button.isChecked()
                self._bridge_status()
            elif kind == "error":
                self._log(f"Bluetooth: {payload}")
            elif kind == "commands_sent":
                self._log("Đã gửi lệnh qua Bluetooth.")
        if self.bluetooth_button.isChecked() and not self._ble.running and not self._testing:
            # A quick off/on can happen before cancellation of the old worker finishes.
            self._ble.start(self._preferred_ble_address())
