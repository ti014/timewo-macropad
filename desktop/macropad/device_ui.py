"""Dialog for the board settings stored in NVS: name, wiring and button timing."""

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from .device import DeviceConfig, DeviceInfo


class DeviceDialog(QDialog):
    """Edit one board's settings; the caller writes them and verifies the echo."""

    def __init__(self, info: DeviceInfo, parent=None) -> None:
        """Show the board's current settings within its reported limits."""
        super().__init__(parent)
        self._info = info
        self.setWindowTitle("Thiết bị")
        layout = QVBoxLayout(self)
        caps = ", ".join(sorted(info.caps)) or "không rõ"
        about = QLabel(
            f"{info.title}\nMẫu firmware: {info.board}\nBoard tự chạy được: {caps}"
        )
        about.setObjectName("muted")
        about.setWordWrap(True)
        layout.addWidget(about)

        form = QFormLayout()
        self.name = QLineEdit(info.config.name)
        self.name.setPlaceholderText("Ví dụ: Remote Phuong")
        self.name.setToolTip(
            f"Tên Bluetooth, tối đa {info.limits.max_name} byte. "
            "Máy đã ghép đôi có thể cần ghép lại để thấy tên mới."
        )
        form.addRow("Tên Bluetooth", self.name)
        self.count = QSpinBox()
        self.count.setRange(1, info.limits.max_buttons)
        self.count.setValue(len(info.config.pins))
        self.count.valueChanged.connect(self._show_pins)
        form.addRow("Số nút", self.count)
        self.pins: list[QComboBox] = []
        for number in range(1, info.limits.max_buttons + 1):
            combo = QComboBox()
            for pin in info.usable_pins:
                combo.addItem(f"GPIO{pin}", pin)
            current = info.config.pins[number - 1] if number <= len(info.config.pins) else None
            index = combo.findData(current)
            combo.setCurrentIndex(index if index >= 0 else min(number - 1, combo.count() - 1))
            form.addRow(f"Nút {number}", combo)
            self.pins.append(combo)
        self._form = form
        self.debounce = QSpinBox()
        self.debounce.setRange(*info.limits.debounce)
        self.debounce.setSuffix(" ms")
        self.debounce.setValue(info.config.debounce_ms)
        self.debounce.setToolTip("Bỏ qua rung tiếp điểm ngắn hơn khoảng này.")
        form.addRow("Debounce", self.debounce)
        self.hold = QSpinBox()
        self.hold.setRange(*info.limits.hold)
        self.hold.setSingleStep(100)
        self.hold.setSuffix(" ms")
        self.hold.setValue(info.config.hold_ms)
        self.hold.setToolTip("Giữ nút cuối lâu như vậy để bật/tắt Bluetooth.")
        form.addRow("Giữ để bật/tắt BLE", self.hold)
        layout.addLayout(form)

        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #b3261e;")
        layout.addWidget(self.error)
        note = QLabel("Lưu xong board tự khởi động lại để áp dụng GPIO và tên mới.")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Lưu vào thiết bị")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Hủy")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._show_pins()

    def _show_pins(self) -> None:
        """Show one GPIO picker per configured button."""
        for number, combo in enumerate(self.pins, start=1):
            self._form.setRowVisible(combo, number <= self.count.value())

    def config(self) -> DeviceConfig:
        """Settings as currently entered (not yet validated)."""
        pins = tuple(combo.currentData() for combo in self.pins[: self.count.value()])
        return DeviceConfig(
            self.name.text().strip(), pins, self.debounce.value(), self.hold.value()
        )

    def accept(self) -> None:
        """Close only when the board would accept these settings."""
        try:
            self._info.validate(self.config())
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        super().accept()
