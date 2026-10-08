"""Vietnamese desktop UI for editing profiles and explicitly enabling USB macros."""

import logging
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QKeyEvent, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .actions import Executor
from .config import (
    FIRMWARE_DIRECT_KINDS,
    FIRMWARE_KIND_IDS,
    KINDS,
    Action,
    load_config,
    save_config,
)
from .hotkeys import is_modifier_key, shortcut_from_event
from .transport import Connection, UsbIdentity, available_ports, find_usb_port, identify_usb_device

HINTS = {
    "lock_screen": "Khóa Windows bằng API hệ thống. Dùng mục này thay cho Win+L.",
    "sequence": "Nh\u1eadp c\u00e1c b\u01b0\u1edbc theo th\u1ee9 t\u1ef1, ng\u0103n c\u00e1ch b\u1eb1ng d\u1ea5u ph\u00edy. V\u00ed d\u1ee5: 1,Enter ho\u1eb7c Ctrl+C,Enter",
    "screenshot": "Ch\u1ee5p to\u00e0n m\u00e0n h\u00ecnh hi\u1ec7n t\u1ea1i v\u00e0o clipboard \u0111\u1ec3 d\u00e1n b\u1eb1ng Ctrl+V.",
    "close_app": "G\u1eedi Alt+F4 \u0111\u1ec3 \u0111\u00f3ng c\u1eeda s\u1ed5/\u1ee9ng d\u1ee5ng \u0111ang \u0111\u01b0\u1ee3c ch\u1ecdn.",
    "none": "Nút này sẽ không thực hiện hành động.",
    "hotkey": "Ví dụ: Ctrl+C, Ctrl+Shift+S, Alt+Tab, Win+E, F5, media_volume_up",
    "text": "Nhập nội dung cần gõ (tối đa 2000 ký tự). Xuống dòng cũng gửi phím Enter.",
    "app": "Chọn file .exe. Không nhập lệnh, tham số hoặc đường dẫn shortcut .lnk.",
    "url": "Ví dụ: https://github.com — mở bằng trình duyệt mặc định.",
}
HOTKEY_PRESETS = (
    ("Alt+F4 — đóng cửa sổ", "Alt+F4"),
    ("Win+Shift+S — chọn vùng chụp", "Win+Shift+S"),
    ("Win+Print_Screen — lưu ảnh màn hình", "Win+Print_Screen"),
    ("Ctrl+Shift+Esc — Task Manager", "Ctrl+Shift+Esc"),
    ("Win+L — khóa máy", "Win+L"),
    ("Alt+Tab — chuyển cửa sổ", "Alt+Tab"),
)
STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 9pt; color: #e8edf5; }
QMainWindow, QWidget#root { background: #111827; }
QGroupBox { background: #1b2639; border: 1px solid #34435b; border-radius: 8px;
            margin-top: 10px; padding: 10px 8px 8px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 14px; }
QFrame#buttonRow { background: #1b2639; border: 1px solid #34435b; border-radius: 6px; }
QLabel#buttonName { color: #dbeafe; font-weight: 600; }
QLabel#tableHeader { color: #8fa3bf; font-size: 8pt; }
QPushButton { background: #2b3b54; border: 1px solid #435572; border-radius: 5px;
              min-height: 27px; padding: 4px 9px; }
QPushButton:hover { background: #3b4f70; }
QPushButton:disabled { color: #76849b; background: #202c40; }
QPushButton#primary { background: #2563eb; border-color: #3b82f6; }
QPushButton#arm:checked { background: #b45309; }
QComboBox, QPlainTextEdit, QLineEdit { background: #111b2c; border: 1px solid #435572;
                                    border-radius: 4px; min-height: 27px; padding: 4px 6px; }
QComboBox QAbstractItemView { background: #1b2639; selection-background-color: #2563eb; }
QLabel#muted { color: #a9b8d0; }
QLabel#title { font-size: 17pt; font-weight: 700; }
QCheckBox { spacing: 8px; }
QMenu { background: #1b2639; }
QMenu::item:selected { background: #2563eb; }
QToolTip { background: #1b2639; color: white; }
"""


def app_icon() -> QIcon:
    """Create a small four-key application icon without external assets.

    Returns:
        An icon suitable for the taskbar and notification area.
    """
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor("#111827"))
    painter = QPainter(pixmap)
    painter.setBrush(QColor("#60a5fa"))
    painter.setPen(QColor("#60a5fa"))
    for x in (8, 35):
        for y in (8, 35):
            painter.drawRoundedRect(x, y, 21, 21, 4, 4)
    painter.end()
    return QIcon(pixmap)


class ShortcutCaptureButton(QPushButton):
    """Button that temporarily consumes one keyboard chord for recording."""

    captured = Signal(str)
    cancelled = Signal()
    invalid = Signal(str)

    def __init__(self) -> None:
        super().__init__("Ghi phím tắt")
        self._recording = False

    def start_recording(self) -> None:
        """Capture the next non-modifier key event received by this button."""
        self._recording = True
        self.setText("Đang ghi… (Esc để hủy)")
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def stop_recording(self) -> None:
        """Return to the normal button state."""
        self._recording = False
        self.setText("Ghi phím tắt")

    def event(self, event) -> bool:
        """Prevent Qt shortcuts from handling a chord before keyPressEvent."""
        if self._recording and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Consume Esc or emit the first complete shortcut chord."""
        if not self._recording:
            super().keyPressEvent(event)
            return
        event.accept()
        if event.isAutoRepeat():
            return
        if event.key() == Qt.Key.Key_Escape:
            self.stop_recording()
            self.cancelled.emit()
            return
        if is_modifier_key(event.key()):
            return
        try:
            shortcut = shortcut_from_event(event)
        except ValueError as exc:
            self.invalid.emit(str(exc))
            return
        self.stop_recording()
        self.captured.emit(shortcut)


class ActionValueEditor(QWidget):
    """Compact value editor that avoids a misleading scrollbar for scalar values.

    Single-line actions such as shortcuts, URLs and executable paths use
    ``QLineEdit``. Text macros keep a small multiline editor so an intentional
    newline remains representable. The public methods mirror the old
    ``QPlainTextEdit`` API because the rest of the UI and existing profiles do
    not need to know which editor is active.
    """

    textChanged = Signal()

    def __init__(self) -> None:
        super().__init__()
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._stack = QStackedWidget(self)
        self._single_line = QLineEdit(self)
        self._multiline = QPlainTextEdit(self)
        self._multiline.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._multiline.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._multiline.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self._stack.addWidget(self._single_line)
        self._stack.addWidget(self._multiline)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)
        self._single_line.textChanged.connect(self._emit_text_changed)
        self._multiline.textChanged.connect(self._emit_text_changed)

    def _emit_text_changed(self, *_args) -> None:
        """Expose one signal regardless of the active Qt editor."""
        self.textChanged.emit()

    def set_multiline(self, enabled: bool) -> None:
        """Switch editor shape while preserving the current value."""
        target_index = 1 if enabled else 0
        if self._stack.currentIndex() == target_index:
            return
        value = self.toPlainText()
        self._stack.setCurrentIndex(target_index)
        self.setPlainText(value)

    def setPlaceholderText(self, text: str) -> None:
        """Set the placeholder on both backing editors."""
        self._single_line.setPlaceholderText(text)
        self._multiline.setPlaceholderText(text)

    def setPlainText(self, text: str) -> None:
        """Set the active editor's complete value."""
        if self._stack.currentIndex() == 0:
            self._single_line.setText(text)
        else:
            self._multiline.setPlainText(text)

    def setText(self, text: str) -> None:
        """QLineEdit-compatible alias used by generic editor code."""
        self.setPlainText(text)

    def toPlainText(self) -> str:
        """Return the active editor's complete value."""
        if self._stack.currentIndex() == 0:
            return self._single_line.text()
        return self._multiline.toPlainText()

    def text(self) -> str:
        """QLineEdit-compatible value accessor."""
        return self.toPlainText()

    def isReadOnly(self) -> bool:
        """Return the read-only state of the active editor."""
        editor = self._single_line if self._stack.currentIndex() == 0 else self._multiline
        return editor.isReadOnly()

    def setReadOnly(self, read_only: bool) -> None:
        """Set both backing editors to the same read-only state."""
        self._single_line.setReadOnly(read_only)
        self._multiline.setReadOnly(read_only)

    def clear(self) -> None:
        """Clear the active editor."""
        if self._stack.currentIndex() == 0:
            self._single_line.clear()
        else:
            self._multiline.clear()


class ButtonEditor(QFrame):
    """Editable assignment for one physical button."""

    def __init__(self, number: int, pin: int) -> None:
        """Build an action selector and literal value editor.

        Args:
            number: Physical button index.
            pin: Firmware GPIO for this button.
        """
        super().__init__()
        self.setObjectName("buttonRow")
        self.setFixedHeight(56)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(6)
        self.title = QLabel(f"BTN{number}  /  GPIO{pin}")
        self.title.setObjectName("buttonName")
        self.title.setFixedWidth(92)
        layout.addWidget(self.title)
        self.kind = QComboBox()
        self.kind.setMinimumWidth(122)
        self.kind.setMaximumWidth(150)
        for key, label in KINDS.items():
            self.kind.addItem(label, key)
        self.preset = QComboBox()
        self.preset.setMinimumWidth(160)
        self.preset.setMaximumWidth(190)
        self.preset.addItem("Chọn phím tắt có sẵn…", "")
        for label, value in HOTKEY_PRESETS:
            self.preset.addItem(label, value)
        self.preset.currentIndexChanged.connect(self._choose_preset)
        self.value = ActionValueEditor()
        self.value.setPlaceholderText("Giá trị hoặc chuỗi phím…")
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")
        self.hint.setMinimumHeight(0)
        self.hint.hide()
        self.browse = QPushButton("Chọn file .exe…")
        self.browse.setMinimumWidth(96)
        self.record = ShortcutCaptureButton()
        self.record.setMinimumWidth(88)
        self.record.clicked.connect(self._start_recording)
        self.record.captured.connect(self._shortcut_recorded)
        self.record.cancelled.connect(self._recording_cancelled)
        self.record.invalid.connect(self._recording_invalid)
        self.browse.clicked.connect(self._browse)
        layout.addWidget(self.kind)
        layout.addWidget(self.preset)
        layout.addWidget(self.value, 1)
        layout.addWidget(self.record)
        layout.addWidget(self.browse)
        self.kind.currentIndexChanged.connect(self._update_hint)
        self._recording = False
        self._update_hint()

    def _update_hint(self) -> None:
        """Explain accepted input for the selected action."""
        kind = self.kind.currentData()
        self.hint.setText(HINTS[kind])
        self.value.set_multiline(kind == "text")
        self.preset.setVisible(True)
        self.preset.setEnabled(kind == "hotkey" and not self._recording)
        self.value.setEnabled(kind in {"hotkey", "sequence", "text", "app", "url"})
        self.record.setEnabled(kind == "hotkey" and not self._recording)
        self.browse.setEnabled(kind == "app")

    def _choose_preset(self, _index: int) -> None:
        """Copy a known system shortcut into the editor."""
        value = self.preset.currentData()
        if not value:
            return
        if value == "Win+L":
            self.kind.setCurrentIndex(self.kind.findData("lock_screen"))
            self.value.clear()
        else:
            self.value.setPlainText(value)
        self.preset.blockSignals(True)
        self.preset.setCurrentIndex(0)
        self.preset.blockSignals(False)

    def _start_recording(self) -> None:
        """Put this editor into keyboard capture mode."""
        if self.kind.currentData() != "hotkey" or self._recording:
            return
        self._recording = True
        self.kind.setEnabled(False)
        self.preset.setEnabled(False)
        self.value.setEnabled(False)
        self.browse.setEnabled(False)
        self.hint.setText("Đang ghi phím tắt: nhấn tổ hợp trên bàn phím. Nhấn Esc để hủy.")
        self.record.start_recording()

    def _finish_recording(self) -> None:
        """Restore normal editor controls after recording ends."""
        self._recording = False
        self.kind.setEnabled(True)
        self.value.setEnabled(True)
        self._update_hint()

    def _shortcut_recorded(self, shortcut: str) -> None:
        """Put the captured chord into the value editor."""
        self.value.setPlainText(shortcut)
        self._finish_recording()

    def _recording_cancelled(self) -> None:
        """Leave the existing shortcut unchanged when Esc is pressed."""
        self._finish_recording()

    def _recording_invalid(self, message: str) -> None:
        """Show a recoverable message while keeping capture active."""
        self.hint.setText(message + " Vui lòng thử lại hoặc nhấn Esc để hủy.")

    def _browse(self) -> None:
        """Select an executable without launching it."""
        path, _ = QFileDialog.getOpenFileName(self, "Chọn ứng dụng", "", "Ứng dụng (*.exe)")
        if path:
            self.value.setPlainText(path)

    def assignment(self) -> Action:
        """Return a validated action from the editor.

        Returns:
            The current user assignment.

        Raises:
            ValueError: If input is invalid.
        """
        kind = self.kind.currentData()
        text = self.value.toPlainText()
        action = Action(kind, text if kind == "text" else text.strip())
        action.validate()
        return action

    def set_assignment(self, action: Action) -> None:
        """Display an action without executing it.

        Args:
            action: Saved assignment to display.
        """
        self.kind.setCurrentIndex(self.kind.findData(action.kind))
        self.value.setPlainText(action.value)


class MainWindow(QMainWindow):
    """Profile editor and serial macro controller with explicit arming."""

    def __init__(self, config_path: Path, *, testing: bool = False) -> None:
        """Initialize UI without connecting or sending keyboard input.

        Args:
            config_path: Local JSON settings path.
            testing: Disable tray and device discovery for isolated UI tests.

        Raises:
            ValueError: If an existing settings file is invalid.
            OSError: If settings cannot be read.
        """
        super().__init__()
        self._path = config_path
        self._config = load_config(config_path)
        self._connection = Connection()
        self._executor = Executor()
        self._loading = False
        self._dirty = False
        self._ready = False
        self._testing = testing
        self._reconnect_target: UsbIdentity | None = None
        self._waiting_for_board = False
        self._resume_macro = False
        self._retry_error: str | None = None
        self.setWindowTitle("Macropad Configurator — USB/BLE v0.9")
        self.setWindowIcon(app_icon())
        self.resize(880, 710)
        self.setMinimumSize(760, 620)
        self.setStyleSheet(STYLE)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(7)
        title = QLabel("Macropad Configurator")
        title.setObjectName("title")
        layout.addWidget(title)
        subtitle = QLabel("4 nút · Kết nối USB · Đổi chức năng không cần nạp lại board")
        subtitle.setObjectName("muted")
        layout.addWidget(subtitle)

        connection_bar = QHBoxLayout()
        self.ports = QComboBox()
        self.ports.setMinimumWidth(220)
        self.refresh = QPushButton("Tìm cổng")
        self.refresh.clicked.connect(self._refresh_ports)
        self.connect_button = QPushButton("Kết nối")
        self.connect_button.clicked.connect(self._toggle_connection)
        self.status = QLabel("Chưa kết nối")
        connection_bar.setSpacing(6)
        connection_bar.addWidget(self.ports, 1)
        connection_bar.addWidget(self.refresh)
        connection_bar.addWidget(self.connect_button)
        connection_bar.addWidget(self.status)
        layout.addLayout(connection_bar)

        profile_bar = QHBoxLayout()
        profile_bar.setSpacing(6)
        profile_bar.addWidget(QLabel("Profile:"))
        self.profiles = QComboBox()
        self.profiles.addItems(self._config.profiles)
        self.profiles.setCurrentText(self._config.active)
        self.profiles.currentTextChanged.connect(self._switch_profile)
        profile_bar.addWidget(self.profiles, 1)
        new_button = QPushButton("Nhân bản profile")
        new_button.clicked.connect(self._new_profile)
        profile_bar.addWidget(new_button)
        self.save_button = QPushButton("Lưu cấu hình")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        profile_bar.addWidget(self.save_button)
        self.sync_button = QPushButton("Đồng bộ board")
        self.sync_button.setEnabled(False)
        self.sync_button.clicked.connect(self._sync_profile)
        profile_bar.addWidget(self.sync_button)
        layout.addLayout(profile_bar)

        table = QVBoxLayout()
        table.setSpacing(5)
        header = QHBoxLayout()
        header.setContentsMargins(8, 0, 8, 0)
        header.setSpacing(6)
        for text, width in (("Nút", 92), ("Loại", 122), ("Preset", 160)):
            label = QLabel(text)
            label.setObjectName("tableHeader")
            label.setFixedWidth(width)
            header.addWidget(label)
        value_header = QLabel("Giá trị")
        value_header.setObjectName("tableHeader")
        header.addWidget(value_header, 1)
        for text, width in (("Ghi", 88), ("Tệp", 96)):
            label = QLabel(text)
            label.setObjectName("tableHeader")
            label.setFixedWidth(width)
            header.addWidget(label)
        table.addLayout(header)
        self.cards = []
        for index, pin in enumerate((3, 4, 5, 6)):
            card = ButtonEditor(index + 1, pin)
            card.kind.currentIndexChanged.connect(self._edited)
            card.value.textChanged.connect(self._edited)
            self.cards.append(card)
            table.addWidget(card)
        table.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.addLayout(table)

        controls = QHBoxLayout()
        self.arm = QPushButton("Bật macro")
        self.arm.setObjectName("arm")
        self.arm.setCheckable(True)
        self.arm.setEnabled(False)
        self.arm.toggled.connect(self._arm_changed)
        self.preview = QCheckBox("Chỉ kiểm tra nút (không phát phím)")
        self.preview.setChecked(True)
        self.preview.toggled.connect(self._pause_macro)
        hide_button = QPushButton("Ẩn xuống khay")
        hide_button.clicked.connect(self._hide_to_tray)
        controls.setSpacing(8)
        controls.addWidget(self.arm)
        controls.addWidget(self.preview, 1)
        controls.addWidget(hide_button)
        layout.addLayout(controls)

        help_label = QLabel(
            "Đóng Serial Monitor → Kết nối → gán nút → Lưu → Đồng bộ board → bỏ kiểm tra → Bật macro."
        )
        help_label.setToolTip(
            "Macro tác động vào cửa sổ đang chọn. Khi sửa cấu hình, macro tự tạm dừng. "
            "Rút/cắm USB sẽ tự khôi phục kết nối và trạng thái macro."
        )
        help_label.setObjectName("muted")
        layout.addWidget(help_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setMinimumHeight(48)
        self.log.setMaximumHeight(70)
        layout.addWidget(self.log)
        self._load_cards()
        self._log("Sẵn sàng. USB dùng app; BLE dùng profile đã đồng bộ lên board.")
        self.tray = QSystemTrayIcon(self.windowIcon(), self)
        self.tray.setToolTip("Macropad Configurator — tạm dừng")
        menu = QMenu(self)
        menu.addAction("Mở cấu hình", self._show_window)
        menu.addAction("Tạm dừng macro", self._pause_macro)
        menu.addSeparator()
        menu.addAction("Thoát", self.close)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        if not testing:
            self.tray.show()
            self._refresh_ports()
        self.timer = QTimer(self)
        self.timer.setInterval(20)
        self.timer.timeout.connect(self._poll)
        if not testing:
            self.timer.start()
        self.settle_timer = QTimer(self)
        self.settle_timer.setSingleShot(True)
        self.settle_timer.timeout.connect(self._settled)
        self.reconnect_timer = QTimer(self)
        self.reconnect_timer.setInterval(1000)
        self.reconnect_timer.timeout.connect(self._retry_connection)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(1000)
        self.watch_timer.timeout.connect(self._watch_connection)
        if not testing:
            self.watch_timer.start()

    def _log(self, message: str) -> None:
        """Append bounded, timestamped status without logging macro text."""
        self.log.appendPlainText(f"{datetime.now(UTC).astimezone():%H:%M:%S}  {message}")
        logging.getLogger("macropad").info(message)

    def _error(self, message: str) -> None:
        """Display a recoverable error and retain the original config."""
        self._log(message)
        QMessageBox.warning(self, "Cần kiểm tra", message)

    def _edited(self) -> None:
        """Disarm as soon as the user starts editing."""
        if not self._loading:
            self._dirty = True
            self._pause_macro()
            self.save_button.setText("Lưu cấu hình *")

    def _load_cards(self) -> None:
        """Display the active profile without marking it dirty."""
        self._loading = True
        for card, action in zip(self.cards, self._config.profiles[self._config.active]):
            card.set_assignment(action)
        self._loading = False
        self._dirty = False
        self.save_button.setText("Lưu cấu hình")

    def _save(self) -> bool:
        """Validate and atomically save all current button assignments."""
        self._pause_macro()
        try:
            updated = deepcopy(self._config)
            updated.profiles[updated.active] = [card.assignment() for card in self.cards]
            save_config(self._path, updated)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return False
        self._config = updated
        self._dirty = False
        self.save_button.setText("Lưu cấu hình")
        self._log(f"Đã lưu profile: {updated.active}.")
        return True

    def _sync_profile(self) -> bool:
        """Save the active profile and copy it to the board's nonvolatile storage."""
        if not self._ready or not self._connection.connected:
            self._error("Hãy kết nối và chờ board đồng bộ trạng thái trước.")
            return False
        if not self._save():
            return False
        unsupported = []
        try:
            for index, action in enumerate(self._config.profiles[self._config.active], start=1):
                encoded = action.value.encode("utf-8").hex().upper() or "-"
                if len(encoded) > 1024:
                    raise ValueError(f"BTN{index} có giá trị quá dài để lưu trên board.")
                self._connection.send_command(
                    f"SYNC {index} {FIRMWARE_KIND_IDS[action.kind]} {encoded}"
                )
                if action.kind not in FIRMWARE_DIRECT_KINDS:
                    unsupported.append(f"BTN{index} ({KINDS[action.kind]})")
            self._connection.send_command("SYNC_COMMIT")
        except (OSError, ValueError) as exc:
            self._error(f"Không đồng bộ được profile lên board: {exc}")
            return False
        message = f"Đã đồng bộ profile '{self._config.active}' lên board."
        if unsupported:
            message += " BLE chỉ chạy trực tiếp: " + ", ".join(unsupported) + "."
        self._log(message)
        return True

    def _resolve_unsaved(self) -> bool:
        """Offer to save before changing profile or exiting."""
        if not self._dirty:
            return True
        answer = QMessageBox.question(
            self,
            "Cấu hình chưa lưu",
            "Bạn muốn lưu các thay đổi vừa sửa?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if answer == QMessageBox.StandardButton.Save:
            return self._save()
        return answer == QMessageBox.StandardButton.Discard

    def _switch_profile(self, name: str) -> None:
        """Persist profile selection, reverting the UI if saving fails."""
        if name == self._config.active or not name:
            return
        self._pause_macro()
        old_name = self._config.active
        if self._resolve_unsaved():
            updated = deepcopy(self._config)
            updated.active = name
            try:
                save_config(self._path, updated)
                self._config = updated
                self._load_cards()
                self._log(f"Đã chọn profile: {name}. Bấm Bật macro khi sẵn sàng.")
                return
            except (OSError, ValueError) as exc:
                self._error(str(exc))
        self.profiles.blockSignals(True)
        self.profiles.setCurrentText(old_name)
        self.profiles.blockSignals(False)

    def _new_profile(self) -> None:
        """Create a named copy of the current saved mapping."""
        self._pause_macro()
        if not self._save():
            return
        name, accepted = QInputDialog.getText(self, "Profile mới", "Tên profile (ví dụ: Coding):")
        name = name.strip()
        if not accepted:
            return
        if not name or name in self._config.profiles:
            self._error("Tên profile không được trống hoặc trùng với profile đã có.")
            return
        updated = deepcopy(self._config)
        updated.profiles[name] = list(updated.profiles[updated.active])
        updated.active = name
        try:
            save_config(self._path, updated)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return
        self._config = updated
        self.profiles.blockSignals(True)
        self.profiles.addItem(name)
        self.profiles.setCurrentText(name)
        self.profiles.blockSignals(False)
        self._load_cards()
        self._log(f"Đã tạo profile: {name}.")

    def _refresh_ports(self) -> None:
        """Prefer an Espressif USB device and preserve a user's current choice."""
        previous = self.ports.currentData()
        self.ports.clear()
        for port, description, esp in available_ports():
            self.ports.addItem(f"{port} — {'ESP32 USB' if esp else description}", port)
        if previous is not None and self.ports.findData(previous) >= 0:
            self.ports.setCurrentIndex(self.ports.findData(previous))

    def _toggle_connection(self) -> None:
        """Connect on demand, explaining the common Serial Monitor conflict."""
        if self._connection.connected or self._waiting_for_board:
            self._disconnect()
            return
        port = self.ports.currentData()
        if not port:
            self._error("Chưa thấy cổng USB. Cắm board, rồi bấm Tìm cổng.")
            return
        try:
            identity = identify_usb_device(port)
            self._begin_connection(port)
        except (OSError, ValueError) as exc:
            self._error(f"Không mở được {port}. Đóng Serial Monitor (Ctrl+C) và thử lại.\n{exc}")
            return
        self._reconnect_target = identity
        if identity is None:
            self._log("Không đọc được định danh USB của ESP32; kết nối này cần cắm lại thủ công.")

    def _begin_connection(self, port: str) -> None:
        """Open the selected board and discard startup traffic before enabling actions."""
        self._connection.open(port)
        try:
            self._connection.request_status()
        except OSError:
            self._connection.close()
            raise
        self.reconnect_timer.stop()
        self._waiting_for_board = False
        self._retry_error = None
        self._ready = False
        if self.ports.findData(port) < 0:
            self.ports.addItem(f"{port} — ESP32 USB", port)
        self.ports.setCurrentIndex(self.ports.findData(port))
        self.connect_button.setText("Ngắt kết nối")
        self.ports.setEnabled(False)
        self.refresh.setEnabled(False)
        self.status.setText(f"{port} · đang đồng bộ")
        self._log(f"Đã mở {port}. Đợi đồng bộ trạng thái nút…")
        self.settle_timer.start(300)

    def _settled(self) -> None:
        """Allow arming only after discarding startup traffic."""
        if self._connection.connected:
            try:
                self._connection.discard_pending()
                self._connection.check_health()
                if not self._connection.confirmed:
                    self.status.setText("Đang chờ firmware trả lời")
                    self.settle_timer.start(300)
                    return
            except OSError as exc:
                self._disconnect(recover=True)
                self._log(f"Mất USB khi đồng bộ: {exc}.")
                return
            self._ready = True
            self.arm.setEnabled(True)
            self.sync_button.setEnabled(True)
            self.status.setText(f"{self.ports.currentData()} · đã kết nối")
            self._log("Đã kết nối. Bạn có thể nhấn nút để kiểm tra.")
            resume = self._resume_macro
            self._resume_macro = False
            if resume and not self._dirty and not self.preview.isChecked():
                self.arm.setChecked(True)
                if self.arm.isChecked():
                    self._log("Đã tự khôi phục macro sau khi cắm lại USB.")

    def _disconnect(self, *, recover: bool = False) -> None:
        """Release USB, preserving prior intent only after unexpected device loss."""
        retry = recover and self._reconnect_target is not None
        resume = (
            retry
            and (self.arm.isChecked() or self._resume_macro)
            and not self._dirty
            and not self.preview.isChecked()
        )
        self.arm.setChecked(False)
        self.arm.setEnabled(False)
        self.sync_button.setEnabled(False)
        self._ready = False
        self.settle_timer.stop()
        try:
            self._connection.close()
        except OSError as exc:
            self._log(f"Lỗi khi đóng cổng USB: {exc}")
        self._waiting_for_board = retry
        self._resume_macro = resume
        self.connect_button.setText("Ngừng tự kết nối" if retry else "Kết nối")
        self.ports.setEnabled(True)
        self.refresh.setEnabled(True)
        if retry:
            self.status.setText("Chờ cắm lại USB")
            self.tray.setToolTip("Macropad Configurator — chờ cắm lại USB")
            self.reconnect_timer.start()
            state = "sẽ khôi phục macro" if resume else "macro vẫn tạm dừng"
            self._log(f"Mất USB. Đang chờ đúng board để tự kết nối lại; {state}.")
        else:
            self._reconnect_target = None
            self.reconnect_timer.stop()
            self.status.setText("Chưa kết nối")
            self._log("Đã ngắt kết nối, macro đang tạm dừng.")

    def _retry_connection(self) -> None:
        """Reconnect only the remembered board; a busy port retries without dialogs."""
        if not self._waiting_for_board or self._reconnect_target is None:
            return
        try:
            port = find_usb_port(self._reconnect_target)
            if port is None:
                return
            self._begin_connection(port)
        except (OSError, ValueError) as exc:
            message = str(exc)
            if message != self._retry_error:
                self._log(
                    f"Chưa kết nối lại được USB: {message}. Sẽ tự thử lại; hãy đóng Serial Monitor nếu đang mở."
                )
                self._retry_error = message

    def _watch_connection(self) -> None:
        """Check OS presence plus firmware liveness independently of serial reads."""
        if self._waiting_for_board or self._reconnect_target is None:
            return
        try:
            port = find_usb_port(self._reconnect_target)
            if not self._connection.connected or port != self.ports.currentData() or port is None:
                self._log("USB đã biến mất hoặc đổi cổng; đang mở lại kết nối.")
                self._disconnect(recover=True)
                return
            self._connection.check_health()
        except OSError as exc:
            self._log(f"Kiểm tra USB thất bại: {exc}")
            self._disconnect(recover=True)

    def _pause_macro(self) -> None:
        """Cancel both active macros and any pending automatic resume."""
        was_pending = self._resume_macro
        self._resume_macro = False
        self.arm.setChecked(False)
        if was_pending:
            self._log("Đã hủy khôi phục macro. Khi cắm lại, macro vẫn tạm dừng.")

    def _arm_changed(self, enabled: bool) -> None:
        """Require valid saved config, clear backlog, then explicitly arm."""
        if not enabled:
            self._resume_macro = False
        if enabled:
            if not self._ready or self.preview.isChecked() or self._dirty:
                self.arm.setChecked(False)
                self._log("Hãy lưu cấu hình và bỏ chọn Chỉ kiểm tra nút trước khi bật macro.")
                return
            try:
                self._connection.discard_pending()
            except OSError as exc:
                self._disconnect(recover=True)
                self._error(str(exc))
                return
        self.arm.setText("Tạm dừng macro" if enabled else "Bật macro")
        self.tray.setToolTip("Macropad Configurator — " + ("đang bật" if enabled else "tạm dừng"))
        self._log(
            "Macro đã bật. Chuyển sang ứng dụng cần dùng." if enabled else "Macro đã tạm dừng."
        )

    def _poll(self) -> None:
        """Read events on the GUI loop and stop safely on USB failure."""
        try:
            for button in self._connection.poll():
                self._handle_press(button)
        except OSError as exc:
            self._disconnect(recover=True)
            self._log(f"Mất kết nối USB: {exc}.")

    def _handle_press(self, button: int) -> None:
        """Execute only when armed and another application has focus."""
        action = self._config.profiles[self._config.active][button - 1]
        if not self._ready or not self.arm.isChecked() or self.preview.isChecked():
            self._log(f"BTN{button}: nhận nút, không chạy macro.")
            return
        if QApplication.activeWindow() is not None:
            self._log(f"BTN{button}: chuyển sang ứng dụng đích hoặc ẩn cửa sổ này để chạy macro.")
            return
        try:
            self._executor.execute(action)
            self._log(f"BTN{button}: đã thực hiện {KINDS[action.kind]}.")
        except (OSError, ValueError) as exc:
            self.arm.setChecked(False)
            self._error(f"Macro bị dừng: {exc}")

    def _hide_to_tray(self) -> None:
        """Hide only if the system tray is available, preserving access to Stop."""
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.hide()
            self.tray.showMessage(
                "Macropad Configurator", "Ứng dụng vẫn chạy. Bấm biểu tượng 4 nút để mở lại."
            )
        else:
            self.showMinimized()

    def _show_window(self) -> None:
        """Restore the editor from the system tray."""
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        """Restore on a normal tray click."""
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_window()

    def closeEvent(self, event: QCloseEvent) -> None:
        """Confirm unsaved edits and release resources before exiting.

        Args:
            event: Qt close request.
        """
        self._pause_macro()
        if not self._resolve_unsaved():
            event.ignore()
            return
        self.timer.stop()
        self.watch_timer.stop()
        self._disconnect()
        self.tray.hide()
        event.accept()
