"""Vietnamese desktop UI for editing profiles and explicitly enabling USB macros."""

import logging
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QColor, QIcon, QKeyEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QSystemTrayIcon,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .actions import Executor
from .bridge_protocol import ButtonPress
from .bridge_ui import BridgeUiMixin
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
    "hotkey": "Nhập tổ hợp hoặc bấm Bắt phím. Ví dụ: Ctrl+Shift+S, Delete, Print_Screen",
    "text": "Dán Unicode qua clipboard (tối đa 2000 ký tự), không qua bộ gõ. Thay nội dung clipboard; ứng dụng đích cần hỗ trợ Ctrl+V.",
    "app": "Chọn file .exe. Không nhập lệnh, tham số hoặc đường dẫn shortcut .lnk.",
    "url": "Ví dụ: https://github.com — mở bằng trình duyệt mặc định.",
}
ACTION_GROUPS = (
    ("Cơ bản", ("none", "hotkey", "sequence", "text", "app", "url")),
    ("Hệ thống", ("lock_screen", "screenshot", "close_app")),
)
STYLE = """
QWidget { font-family: 'Segoe UI'; font-size: 9pt; color: #171717; }
QMainWindow, QWidget#root, QScrollArea { background: #f6edda; }
QScrollArea { border: none; }
QGroupBox { background: #fffdf5; border: 2px solid #171717; border-radius: 10px;
            margin-top: 8px; padding: 6px 4px 4px; font-weight: 800; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 5px; }
QFrame#buttonRow { background: #fffdf5; border: 2px solid #171717; border-radius: 10px; }
QFrame#buttonRow[active="true"] { border-color: #2563eb; }
QLabel#buttonName { color: #171717; font-weight: 800; }
QLabel#tableHeader { color: #171717; font-size: 8pt; font-weight: 800; }
QPushButton, QToolButton { background: #ffd43b; color: #171717; border: 2px solid #171717; border-radius: 8px;
              min-height: 22px; padding: 3px 8px; font-weight: 700; }
QPushButton:hover { background: #ffe274; }
QPushButton:pressed { background: #f4b900; }
QPushButton:disabled { color: #777064; background: #e5dcc9; border-color: #777064; }
QPushButton#primary { background: #ff6b9a; }
QPushButton#primary:hover { background: #ff8ab0; }
QPushButton#arm:checked { background: #7bdc55; }
QPushButton:checked { background: #65cfff; }
QToolButton { background: #fffdf5; }
QToolButton:hover { background: #e9dfcb; }
QComboBox, QPlainTextEdit, QLineEdit { background: #ffffff; color: #171717; border: 2px solid #171717;
                                    border-radius: 8px; min-height: 22px; padding: 3px 6px; }
QComboBox QAbstractItemView { background: #ffffff; color: #171717; border: 2px solid #171717;
                              selection-background-color: #65cfff; selection-color: #171717; }
QLabel#muted { color: #5f584c; }
QLabel#title { color: #171717; font-size: 15pt; font-weight: 800; }
QCheckBox { spacing: 8px; font-weight: 600; }
QMenu { background: #fffdf5; color: #171717; border: 2px solid #171717; }
QMenu::item:selected { background: #65cfff; }
QToolTip { background: #171717; color: #fffdf5; border: 1px solid #171717; }
"""


def add_hard_shadow(widget: QWidget, offset: int = 4) -> None:
    """Give a widget the zero-blur offset shadow used by Neo-Brutalism."""
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(0)
    effect.setOffset(offset, offset)
    effect.setColor(QColor("#171717"))
    widget.setGraphicsEffect(effect)


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


class MarkedCheckBox(QCheckBox):
    """Checkbox with a high-contrast tick instead of a colored fill."""

    def paintEvent(self, _event) -> None:
        """Draw a plain square and a visible check mark."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor("#171717" if self.isEnabled() else "#777064")
        indicator = QRect(1, (self.height() - 18) // 2, 18, 18)
        painter.setPen(QPen(color, 2))
        painter.setBrush(QColor("#ffffff"))
        painter.drawRoundedRect(indicator, 3, 3)
        if self.isChecked():
            painter.setPen(QPen(color, 2.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(5, indicator.center().y(), 9, indicator.bottom() - 4)
            painter.drawLine(9, indicator.bottom() - 4, indicator.right() - 3, indicator.top() + 4)
        painter.setPen(color)
        painter.drawText(
            QRect(28, 0, max(0, self.width() - 28), self.height()),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self.text(),
        )
        if self.hasFocus():
            painter.setPen(QPen(color, 1, Qt.PenStyle.DotLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        painter.end()


class QuickKeyBar(QGroupBox):
    """Clickable modifiers and common keys for the selected button row."""

    keyPressed = Signal(str)

    def __init__(self) -> None:
        super().__init__("Phím nhanh — Nút 1")
        self.modifier_buttons: dict[str, QPushButton] = {}
        self.key_buttons: dict[str, QPushButton] = {}
        layout = QGridLayout(self)
        layout.setContentsMargins(6, 2, 6, 4)
        layout.setHorizontalSpacing(5)
        layout.setVerticalSpacing(4)
        self.note = QLabel("Chọn phím bổ trợ, rồi chọn phím chính.")
        self.note.setObjectName("muted")
        self.note.setWordWrap(True)
        layout.addWidget(self.note, 0, 0, 1, 4)
        for column, token in enumerate(("ctrl", "alt", "shift", "win"), start=4):
            label = token.title()
            button = QPushButton(label)
            button.setCheckable(True)
            button.setToolTip(f"Thêm {token.title()} vào tổ hợp")
            button.toggled.connect(
                lambda checked, button=button, label=label: button.setText(
                    f"{label} ✓" if checked else label
                )
            )
            self.modifier_buttons[token] = button
            layout.addWidget(button, 0, column)
        rows = (
            ("A", "C", "V", "X", "Z", "S", "L", "F4"),
            ("Tab", "Enter", "Backspace", "Delete", "Esc", "Space", "Print_Screen"),
        )
        for row, keys in enumerate(rows, start=1):
            for column, token in enumerate(keys):
                label = "Print Screen" if token == "Print_Screen" else token
                button = QPushButton(label)
                button.setToolTip(f"Gán phím {label}; không gửi phím vào máy tính.")
                button.clicked.connect(lambda _checked=False, value=token: self.keyPressed.emit(value))
                self.key_buttons[token.lower()] = button
                layout.addWidget(button, row, column)
        self.setMinimumHeight(self.sizeHint().height())

    def clear_modifiers(self) -> None:
        """Clear modifier toggles after a shortcut is committed or focus changes."""
        for button in self.modifier_buttons.values():
            button.setChecked(False)

    def selected_modifiers(self) -> list[str]:
        """Return selected modifiers in stable keyboard order."""
        return [token for token, button in self.modifier_buttons.items() if button.isChecked()]


class ShortcutCaptureButton(QPushButton):
    """Capture one keyboard chord for the adjacent shortcut field."""

    captured = Signal(str)
    cancelled = Signal()
    invalid = Signal(str)

    def __init__(self) -> None:
        super().__init__("Bắt phím")
        self._recording = False

    def start_recording(self) -> None:
        """Capture the next complete shortcut chord."""
        self._recording = True
        self.setText("Nhấn phím…")
        self.setToolTip("Nhấn tổ hợp cần ghi. Nhấn Esc để hủy.")
        self.setFocus(Qt.FocusReason.OtherFocusReason)

    def stop_recording(self) -> None:
        """Restore the compact idle label."""
        self._recording = False
        self.setText("Bắt phím")
        self.setToolTip("Ghi một tổ hợp phím từ bàn phím.")

    def event(self, event) -> bool:
        """Prevent Qt shortcuts from consuming the chord first."""
        if self._recording and event.type() == QEvent.Type.ShortcutOverride:
            event.accept()
            return True
        return super().event(event)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Consume Esc or emit the first complete chord."""
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
        if not shortcut:
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
        self.setFixedHeight(32)
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

    captureStarted = Signal()
    captureFinished = Signal()
    focused = Signal()

    def __init__(self, number: int, pin: int) -> None:
        """Build an action selector and literal value editor.

        Args:
            number: Physical button index.
            pin: Firmware GPIO for this button.
        """
        super().__init__()
        self.setObjectName("buttonRow")
        self.setFixedHeight(46)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(6)
        self.title = QLabel(f"Nút {number}")
        self.title.setToolTip(f"BTN{number} / GPIO{pin}")
        self.title.setObjectName("buttonName")
        self.title.setFixedWidth(52)
        layout.addWidget(self.title)
        self.kind = QComboBox()
        self.kind.setFixedWidth(230)
        for group_index, (_group_name, keys) in enumerate(ACTION_GROUPS):
            if group_index:
                self.kind.insertSeparator(self.kind.count())
            for key in keys:
                self.kind.addItem(KINDS[key], key)
        self.value = ActionValueEditor()
        self.value.setPlaceholderText("Giá trị hoặc chuỗi phím…")
        self.summary = QLabel()
        self.summary.setObjectName("muted")
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        self.hint.setObjectName("muted")
        self.hint.setMinimumHeight(0)
        self.hint.hide()
        self.browse = QPushButton("Chọn file .exe…")
        self.browse.setMinimumWidth(96)
        self.record = ShortcutCaptureButton()
        self.record.setMinimumWidth(82)
        self.record.clicked.connect(self._start_recording)
        self.record.captured.connect(self._shortcut_recorded)
        self.record.cancelled.connect(self._recording_cancelled)
        self.record.invalid.connect(self._recording_invalid)
        self.browse.clicked.connect(self._browse)
        for widget in (
            self,
            self.title,
            self.summary,
            self.kind,
            self.value,
            self.value._single_line,
            self.value._multiline,
            self.record,
            self.browse,
        ):
            widget.installEventFilter(self)
        layout.addWidget(self.kind)
        layout.addWidget(self.value, 1)
        tools = QWidget()
        tools.setFixedWidth(118)
        tool_layout = QHBoxLayout(tools)
        tool_layout.setContentsMargins(0, 0, 0, 0)
        tool_layout.addWidget(self.record)
        tool_layout.addWidget(self.browse)
        layout.addWidget(self.summary, 1)
        layout.addWidget(tools)
        self.kind.currentIndexChanged.connect(self._update_hint)
        self._recording = False
        add_hard_shadow(self)
        self._update_hint()

    def eventFilter(self, watched, event) -> bool:
        """Mark this row active whenever one of its controls receives focus."""
        if event.type() in {QEvent.Type.FocusIn, QEvent.Type.MouseButtonPress}:
            self.focused.emit()
        return super().eventFilter(watched, event)

    def set_active(self, active: bool) -> None:
        """Highlight the row targeted by the quick-key bar."""
        self.setProperty("active", active)
        self.style().unpolish(self)
        self.style().polish(self)

    def _update_hint(self) -> None:
        """Explain accepted input for the selected action."""
        kind = self.kind.currentData()
        if not isinstance(kind, str):
            return
        self.hint.setText(HINTS[kind])
        editable = kind in {"hotkey", "sequence", "text", "app", "url"}
        self.value.setVisible(editable)
        self.summary.setVisible(not editable)
        self.summary.setText(
            {
                "none": "Không thực hiện hành động",
                "lock_screen": "Khóa Windows",
                "screenshot": "Ảnh vào clipboard",
                "close_app": "Gửi Alt+F4",
            }.get(kind, "")
        )
        self.value.setToolTip(self.hint.text())
        self.summary.setToolTip(self.hint.text())
        self.value.set_multiline(kind == "text")
        self.value.setEnabled(editable)
        self.record.setVisible(kind == "hotkey")
        self.record.setEnabled(kind == "hotkey" and not self._recording)
        self.browse.setVisible(kind == "app")
        self.browse.setEnabled(kind == "app")

    def _start_recording(self) -> None:
        """Temporarily capture one shortcut into the value editor."""
        if self.kind.currentData() != "hotkey" or self._recording:
            return
        self._recording = True
        self.kind.setEnabled(False)
        self.value.setEnabled(False)
        self.browse.setEnabled(False)
        self.record.setEnabled(True)
        self.hint.setText("Nhấn tổ hợp phím trên bàn phím. Nhấn Esc để hủy.")
        self.captureStarted.emit()
        self.record.start_recording()

    def _finish_recording(self) -> None:
        """Restore the normal controls after capture ends."""
        self._recording = False
        self.kind.setEnabled(True)
        self.value.setEnabled(True)
        self._update_hint()
        self.captureFinished.emit()

    def _shortcut_recorded(self, shortcut: str) -> None:
        """Put the captured shortcut into the value editor."""
        self.value.setPlainText(shortcut)
        self._finish_recording()

    def _recording_cancelled(self) -> None:
        """Keep the previous value when capture is cancelled."""
        self._finish_recording()

    def _recording_invalid(self, message: str) -> None:
        """Show a recoverable error while keeping capture active."""
        self.hint.setText(message + " Thử lại hoặc nhấn Esc để hủy.")

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
        if not isinstance(kind, str):
            raise TypeError("Hãy chọn một loại hành động.")
        text = self.value.toPlainText()
        value = text if kind == "text" else text.strip()
        if kind in {"none", "lock_screen", "screenshot", "close_app"}:
            value = ""
        action = Action(kind, value)
        action.validate()
        return action

    def set_assignment(self, action: Action) -> None:
        """Display an action without executing it.

        Args:
            action: Saved assignment to display.
        """
        self.kind.setCurrentIndex(self.kind.findData(action.kind))
        self.value.setPlainText(action.value)


class MainWindow(BridgeUiMixin, QMainWindow):
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
        self._init_bridge()
        self._reconnect_target: UsbIdentity | None = None
        self._waiting_for_board = False
        self._resume_macro = False
        self._retry_error: str | None = None
        self.setWindowTitle("timewo-macropad — USB/BLE v0.10")
        self.setWindowIcon(app_icon())
        available = self.screen().availableGeometry()
        self.setMinimumSize(min(760, available.width() - 32), min(440, available.height() - 64))
        self.resize(min(860, available.width() - 32), min(600, available.height() - 64))
        self.setStyleSheet(STYLE)
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(10, 8, 10, 10)
        layout.setSpacing(8)
        heading = QHBoxLayout()
        heading.setSpacing(8)
        title = QLabel("timewo-macropad")
        title.setObjectName("title")
        heading.addWidget(title)
        heading.addStretch()
        layout.addLayout(heading)

        device_group = QWidget()
        device_bar = QHBoxLayout(device_group)
        device_bar.setContentsMargins(0, 0, 3, 3)
        self.ports = QComboBox()
        self.ports.setMinimumContentsLength(18)
        self.ports.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.refresh = QPushButton("Làm mới")
        self.refresh.clicked.connect(self._refresh_ports)
        self.connect_button = QPushButton("Kết nối")
        self.connect_button.clicked.connect(self._toggle_connection)
        self.status = QLabel("Chưa kết nối")
        self.status.setWordWrap(True)
        device_bar.setSpacing(6)
        device_bar.addWidget(self.ports, 1)
        device_bar.addWidget(self.refresh)
        device_bar.addWidget(self.connect_button)
        device_bar.addWidget(self.status)
        layout.addWidget(device_group)

        self.profiles = QComboBox()
        self.profiles.setMinimumContentsLength(12)
        self.profiles.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon
        )
        self.profiles.setMaximumWidth(220)
        self.profiles.addItems(self._config.profiles)
        self.profiles.setCurrentText(self._config.active)
        self.profiles.currentTextChanged.connect(self._switch_profile)
        heading.addWidget(QLabel("Profile:"))
        heading.addWidget(self.profiles, 1)
        self.options = QToolButton()
        self.options.setText("Tùy chọn")
        self.options.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        options_menu = QMenu(self.options)
        options_menu.addAction("Nhân bản profile", self._new_profile)
        options_menu.addSeparator()
        self.log_toggle = options_menu.addAction("Hiện nhật ký")
        self.log_toggle.setCheckable(True)
        options_menu.addAction("Ẩn xuống khay", self._hide_to_tray)
        self.options.setMenu(options_menu)
        self._build_bridge_controls(device_bar, options_menu)
        heading.addWidget(self.options)

        # Only the editors scroll: connection and primary actions remain reachable.
        self.editor_scroll = QScrollArea()
        self.editor_scroll.setWidgetResizable(True)
        editor_page = QWidget()
        editor_page.setObjectName("root")
        editor_layout = QVBoxLayout(editor_page)
        editor_layout.setContentsMargins(0, 0, 0, 0)
        editor_layout.setSpacing(8)
        editor_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.editor_scroll.setWidget(editor_page)
        layout.addWidget(self.editor_scroll, 1)

        assignment_group = QGroupBox("Gán chức năng cho 4 nút")
        table = QVBoxLayout(assignment_group)
        table.setContentsMargins(6, 4, 6, 6)
        table.setSpacing(5)
        header = QHBoxLayout()
        header.setContentsMargins(6, 0, 6, 0)
        header.setSpacing(6)
        for text, width in (("Nút", 52), ("Chức năng", 230)):
            label = QLabel(text)
            label.setObjectName("tableHeader")
            label.setFixedWidth(width)
            header.addWidget(label)
        value_header = QLabel("Giá trị")
        value_header.setObjectName("tableHeader")
        header.addWidget(value_header, 1)
        header.addSpacing(118)
        table.addLayout(header)
        self.cards = []
        for index, pin in enumerate((3, 4, 5, 6)):
            card = ButtonEditor(index + 1, pin)
            card.kind.currentIndexChanged.connect(self._edited)
            card.kind.currentIndexChanged.connect(self._refresh_quick_keys)
            card.value.textChanged.connect(self._edited)
            card.captureStarted.connect(self._pause_macro)
            card.captureStarted.connect(self._refresh_quick_keys)
            card.captureFinished.connect(self._refresh_quick_keys)
            card.focused.connect(lambda card=card: self._select_card(card))
            self.cards.append(card)
            table.addWidget(card)
        table.setAlignment(Qt.AlignmentFlag.AlignTop)
        assignment_group.setMinimumHeight(assignment_group.sizeHint().height())
        editor_layout.addWidget(assignment_group)

        self.active_card = self.cards[0]
        self.quick_keys = QuickKeyBar()
        self.quick_keys.keyPressed.connect(self._quick_key_pressed)
        editor_layout.addWidget(self.quick_keys)
        self._select_card(self.active_card)

        run_group = QWidget()
        controls = QHBoxLayout(run_group)
        controls.setContentsMargins(0, 0, 3, 3)
        self.arm = QPushButton("Bật macro")
        self.arm.setObjectName("arm")
        self.arm.setCheckable(True)
        self.arm.setEnabled(False)
        self.arm.toggled.connect(self._arm_changed)
        self.preview = MarkedCheckBox("Chỉ kiểm tra nút")
        self.preview.setToolTip("Nhận tín hiệu từ nút nhưng không thực hiện macro.")
        self.preview.setChecked(True)
        self.preview.toggled.connect(self._pause_macro)
        self.save_button = QPushButton("Lưu cấu hình")
        self.save_button.setObjectName("primary")
        self.save_button.clicked.connect(self._save)
        self.save_button.setToolTip("Lưu profile vào máy tính và chép vào board đang kết nối.")
        add_hard_shadow(self.arm, offset=3)
        for action_button in (self.refresh, self.connect_button, self.save_button):
            add_hard_shadow(action_button, offset=3)
        controls.setSpacing(8)
        controls.addWidget(self.preview, 1)
        controls.addWidget(self.save_button)
        controls.addWidget(self.arm)
        layout.addWidget(run_group)

        help_label = QLabel(
            "App đang mở: app chạy macro. Tắt app hoặc sang máy khác: board tự gõ phím tắt qua Bluetooth."
        )
        help_label.setToolTip(
            "Lưu là board nhận profile ngay. Mở app, URL và văn bản chỉ chạy khi app đang mở. "
            "Macro tác động vào cửa sổ đang chọn. Khi sửa cấu hình, macro tự tạm dừng. "
            "Rút/cắm USB sẽ tự khôi phục kết nối và trạng thái macro."
        )
        help_label.setObjectName("muted")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(200)
        self.log.setMinimumHeight(48)
        self.log.setMaximumHeight(70)
        self.log.hide()
        self.log_toggle.toggled.connect(self.log.setVisible)
        editor_layout.addWidget(self.log)
        self._load_cards()
        self._log("Sẵn sàng. App mở thì app chạy macro; tắt app thì board tự gõ phím tắt đã lưu.")
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
            if self._bridge_settings.value("ble/enabled", False, type=bool):
                self.bluetooth_button.setChecked(True)

    def _select_card(self, card: ButtonEditor) -> None:
        """Set the target row for quick-key clicks and show it clearly."""
        changed = self.active_card is not card
        self.active_card = card
        for candidate in self.cards:
            candidate.set_active(candidate is card)
        if hasattr(self, "quick_keys"):
            if changed:
                self.quick_keys.clear_modifiers()
            self._refresh_quick_keys()

    def _refresh_quick_keys(self) -> None:
        """Keep quick keys aligned with the selected action and capture state."""
        if not hasattr(self, "quick_keys"):
            return
        card = self.active_card
        number = self.cards.index(card) + 1
        self.quick_keys.setTitle(f"Phím nhanh — Nút {number}")
        kind = card.kind.currentData()
        enabled = kind in {"hotkey", "sequence"} and not any(c._recording for c in self.cards)
        self.quick_keys.setEnabled(enabled)
        if not enabled:
            self.quick_keys.clear_modifiers()
        self.quick_keys.note.setText(
            "Chọn phím bổ trợ, rồi chọn phím chính."
            if enabled
            else "Chọn Phím tắt hoặc Chuỗi phím để dùng."
        )

    def _quick_key_pressed(self, key: str) -> None:
        """Commit a shortcut assembled from the quick-key bar."""
        if not self.quick_keys.isEnabled():
            return
        modifiers = self.quick_keys.selected_modifiers()
        value = "+".join([*(modifier.title() for modifier in modifiers), key])
        if self.active_card.kind.currentData() == "sequence":
            existing = self.active_card.value.toPlainText().strip()
            value = f"{existing},{value}" if existing else value
        self.active_card.value.setPlainText(value)
        self.quick_keys.clear_modifiers()

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
            self._update_save_label()

    def _update_save_label(self) -> None:
        """Mark local configuration edits without changing the button meaning."""
        self.save_button.setText("Lưu cấu hình" + (" *" if self._dirty else ""))

    def _load_cards(self) -> None:
        """Display the active profile without marking it dirty."""
        self._loading = True
        for card, action in zip(self.cards, self._config.profiles[self._config.active]):
            card.set_assignment(action)
        self._loading = False
        self._dirty = False
        self._update_save_label()

    def _save(self, *, push: bool = True) -> bool:
        """Validate and atomically save all current button assignments.

        Args:
            push: Also copy the saved profile to a connected board, so it keeps
                working on other machines and after the app closes.
        """
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
        self._update_save_label()
        self._log(f"Đã lưu profile: {updated.active}.")
        if push and self._board_linked():
            self._push_profile()
        return True

    def _board_linked(self) -> bool:
        return (self._ready and self._connection.connected) or self._ble_ready

    def _sync_profile(self) -> bool:
        """Save the active profile and copy it to the board's nonvolatile storage."""
        if not self._board_linked():
            self._error("Hãy kết nối và chờ board đồng bộ trạng thái trước.")
            return False
        return self._save(push=False) and self._push_profile(report=self._error)

    def _push_profile(self, report=None) -> bool:
        """Copy the saved active profile to the board; unchanged entries cost no flash."""
        report = report or self._log
        unsupported = []
        commands = []
        try:
            for index, action in enumerate(self._config.profiles[self._config.active], start=1):
                # The board never runs these kinds, so it needs no copy of their value.
                direct = action.kind in FIRMWARE_DIRECT_KINDS
                encoded = (action.value.encode("utf-8").hex().upper() if direct else "") or "-"
                if len(encoded) > 1024:
                    raise ValueError(f"BTN{index} có giá trị quá dài để lưu trên board.")
                commands.append(f"SYNC {index} {FIRMWARE_KIND_IDS[action.kind]} {encoded}")
                if not direct:
                    unsupported.append(f"BTN{index} ({KINDS[action.kind]})")
            commands.append("SYNC_COMMIT")
            if self._ready and self._connection.connected:
                for command in commands:
                    self._connection.send_command(command)
            else:
                self._ble.send_commands(commands)
        except (OSError, ValueError) as exc:
            report(f"Không đồng bộ được profile lên board: {exc}")
            return False
        message = f"Board đã có profile '{self._config.active}'; tắt app board vẫn tự chạy phím tắt."
        if unsupported:
            message += " Cần app mở: " + ", ".join(unsupported) + "."
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
                if self._board_linked():
                    self._push_profile()
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
        self._update_save_label()
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
            self._check_bridge_identity()
            self._update_save_label()
            self.arm.setEnabled(True)
            self.status.setText(f"{self.ports.currentData()} · đã kết nối")
            self._log("Đã kết nối. Bạn có thể nhấn nút để kiểm tra.")
            # The board may hold an older profile (edited offline, other machine).
            self._push_profile()
            if isinstance(self._connection.bridge_session, int):
                self._apply_device_mode(self._connection.standalone)
            self._bridge_status()
            resume = self._resume_macro
            self._resume_macro = False
            if resume and not self._dirty and not self.preview.isChecked():
                self.arm.setChecked(True)
                if self.arm.isChecked():
                    self._log("Đã tự khôi phục macro sau khi cắm lại USB.")

    def _disconnect(self, *, recover: bool = False) -> None:
        """Release USB, preserving prior intent only after unexpected device loss."""
        retry = recover and self._reconnect_target is not None
        ble_handover = recover and self._ble_ready and not self._standalone
        resume = (
            (retry or ble_handover or (recover and self.bluetooth_button.isChecked()))
            and (self.arm.isChecked() or self._resume_macro)
            and not self._dirty
            and not self.preview.isChecked()
        )
        self.arm.setChecked(False)
        self.arm.setEnabled(False)
        self._ready = False
        self._update_save_label()
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
            self._log("Đã ngắt kết nối; board tự gõ phím tắt đã lưu qua Bluetooth.")
        if ble_handover:
            self.arm.setEnabled(True)
            self._bridge_status()
            if resume:
                self._resume_macro = False
                self.arm.setChecked(True)

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
        self._ble.set_capture(False)
        self.arm.setChecked(False)
        if was_pending:
            self._log("Đã hủy khôi phục macro. Khi cắm lại, macro vẫn tạm dừng.")

    def _arm_changed(self, enabled: bool) -> None:
        """Require valid saved config, clear backlog, then explicitly arm."""
        if not enabled:
            self._resume_macro = False
        if enabled:
            if not (self._ready or self._ble_ready) or self._standalone or self.preview.isChecked() or self._dirty:
                self.arm.setChecked(False)
                self._log("Hãy lưu cấu hình và bỏ chọn Chỉ kiểm tra nút trước khi bật macro.")
                return
            try:
                self._connection.discard_pending()
            except OSError as exc:
                self._disconnect(recover=True)
                self._error(str(exc))
                return
        try:
            self._ble.set_capture(enabled)
        except OSError as exc:
            self.arm.setChecked(False)
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
            events = self._connection.poll()
            self._check_bridge_identity()
            if (self._ready and isinstance(self._connection.bridge_session, int)
                    and self._connection.standalone != self._standalone):
                self._apply_device_mode(self._connection.standalone)
            for button in events:
                if self._ready:
                    self._handle_press(button)
                else:
                    self._log(f"BTN{button}: nhận nút, đang chờ đồng bộ USB.")
        except OSError as exc:
            self._disconnect(recover=True)
            self._log(f"Mất kết nối USB: {exc}.")
        self._poll_ble()
        if self._ready:
            self._bridge_status()

    def _handle_press(self, button: int) -> None:
        """Execute only when armed and another application has focus."""
        if isinstance(button, ButtonPress) and not self._event_gate.accept(button):
            return
        action = self._config.profiles[self._config.active][button - 1]
        if not (self._ready or self._ble_ready) or self._standalone or not self.arm.isChecked() or self.preview.isChecked():
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
        self._ble.stop()
        self._disconnect()
        self.tray.hide()
        event.accept()
