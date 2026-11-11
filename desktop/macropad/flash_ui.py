"""Set up a new board or update its firmware with esptool, then check it answers."""

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
)

from .device import CHIP_TITLES, NO_BLE_CHIPS, parse_info
from .firmware import (
    Package,
    default_firmware_dir,
    detect_args,
    find_packages,
    parse_chip,
    parse_progress,
    run_esptool,
    write_args,
)
from .transport import Connection, available_ports, find_usb_port, identify_usb_device

VERIFY_ATTEMPTS = 25
VERIFY_INTERVAL_MS = 800


class _Worker(QObject):
    """Carries esptool output from its thread to the GUI thread."""

    output = Signal(str)
    finished = Signal(int)

    def start(self, args: list[str]) -> None:
        """Run esptool on a daemon thread; ``finished`` is always emitted."""

        def run() -> None:
            code = 1
            try:
                code = run_esptool(args, self.output.emit)
            finally:
                self.finished.emit(code)

        threading.Thread(target=run, name="esptool", daemon=True).start()


class FlashDialog(QDialog):
    """Choose port and package, write it, then confirm the new firmware replies."""

    def __init__(self, release_port: Callable[[str], None], parent=None, port: str | None = None):
        """Build the dialog.

        Args:
            release_port: Called before esptool opens a port the main window may hold.
            parent: Owner window.
            port: Port to preselect.
        """
        super().__init__(parent)
        self.setWindowTitle("Nạp mới / Cập nhật firmware qua USB")
        self.resize(700, 620)
        self._release_port = release_port
        self._packages: list[Package] = []
        self._chip: str | None = None
        self._output = ""
        self._busy = False
        self._target: Package | None = None
        self._identity = None
        self._attempt = 0
        self.flashed_port: str | None = None
        self._worker = _Worker()
        self._worker.output.connect(self._append)
        self._worker.finished.connect(self._esptool_finished)
        self._verify_timer = QTimer(self)
        self._verify_timer.setSingleShot(True)
        self._verify_timer.timeout.connect(self._verify)

        layout = QVBoxLayout(self)
        help_text = QLabel(
            "Chỉ nạp khi bạn bấm Nạp và xác nhận. Cắm USB hoặc Kết nối không nạp firmware. "
            "Không cần Bluetooth. Không rút cáp trong lúc nạp."
        )
        help_text.setWordWrap(True)
        layout.addWidget(help_text)
        layout.addWidget(QLabel("1. Chọn cổng USB, rồi bấm Nhận diện chip"))
        row = QHBoxLayout()
        self.ports = QComboBox()
        for name, description, likely in available_ports():
            self.ports.addItem(f"{name} — {description}" + (" (ESP32?)" if likely else ""), name)
        if port is not None and self.ports.findData(port) >= 0:
            self.ports.setCurrentIndex(self.ports.findData(port))
        self.refresh = QPushButton("Tìm lại cổng")
        self.refresh.clicked.connect(self._refresh_ports)
        self.detect = QPushButton("Nhận diện chip")
        self.detect.clicked.connect(self._detect)
        row.addWidget(self.ports, 1)
        row.addWidget(self.refresh)
        row.addWidget(self.detect)
        self.ports.currentIndexChanged.connect(self._port_changed)
        layout.addLayout(row)
        self.chip_label = QLabel("Chưa nhận diện chip.")
        self.chip_label.setWordWrap(True)
        layout.addWidget(self.chip_label)

        layout.addWidget(QLabel("2. Chọn mẫu board (số nút, GPIO mặc định) và firmware"))
        row = QHBoxLayout()
        self.package = QComboBox()
        self.folder_button = QPushButton("Thư mục firmware…")
        self.folder_button.clicked.connect(self._choose_folder)
        row.addWidget(self.package, 1)
        row.addWidget(self.folder_button)
        layout.addLayout(row)

        layout.addWidget(QLabel("3. Cách nạp"))
        self.update_mode = QRadioButton("Cập nhật / Nạp đè — chỉ ghi firmware, giữ cấu hình")
        self.full_mode = QRadioButton(
            "Nạp mới / Khôi phục — ghi bootloader, bảng phân vùng và firmware"
        )
        self.update_mode.setChecked(True)
        self.erase = QCheckBox("Xóa toàn bộ flash trước khi ghi (mất mọi cấu hình trên board)")
        self.erase.setEnabled(False)
        self.full_mode.toggled.connect(self.erase.setEnabled)
        self.full_mode.toggled.connect(lambda on: on or self.erase.setChecked(False))
        for widget in (self.update_mode, self.full_mode, self.erase):
            layout.addWidget(widget)
        self.package_hint = QLabel()
        self.package_hint.setWordWrap(True)
        layout.addWidget(self.package_hint)
        self.package.currentIndexChanged.connect(self._update_flash_state)

        row = QHBoxLayout()
        self.flash = QPushButton("Nạp và kiểm tra")
        self.flash.setObjectName("primary")
        self.flash.clicked.connect(self._flash)
        self.close_button = QPushButton("Đóng")
        self.close_button.clicked.connect(self.reject)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        row.addWidget(self.progress, 1)
        row.addWidget(self.flash)
        row.addWidget(self.close_button)
        layout.addLayout(row)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(2000)
        layout.addWidget(self.log, 1)
        self._load_packages(default_firmware_dir())

    # -- packages ---------------------------------------------------------------

    def _load_packages(self, folder: Path) -> None:
        """Read every package in ``folder`` and refresh the list."""
        self._folder = folder
        self._packages, errors = find_packages(folder) if folder.is_dir() else ([], [])
        for error in errors:
            self._note(error)
        if not self._packages:
            self._note(
                f"Không có gói firmware trong {folder}. "
                "Chạy build-firmware.ps1 hoặc chọn thư mục chứa gói."
            )
        self._fill_packages()

    def _fill_packages(self) -> None:
        """List packages for the detected chip only, or all before detection."""
        self.package.clear()
        for package in self._packages:
            if self._chip is None or package.chip == self._chip:
                self.package.addItem(package.label, package)
        self._update_flash_state()

    def _update_flash_state(self) -> None:
        """Require detection for this port before any firmware write."""
        self.flash.setEnabled(
            self._chip is not None and self.package.count() > 0
            and bool(self.ports.currentData()) and not self._busy
        )
        if not self._packages:
            self.package_hint.setText(
                "Chưa có gói firmware. Tại thư mục repo chạy: "
                "./build-firmware.ps1 -Env esp32c3 (board 4 nút C3), "
                "rồi bấm Thư mục firmware… và chọn dist/firmware."
            )
        elif self._chip is None:
            self.package_hint.setText("Bấm Nhận diện chip trước khi nạp. Chưa ghi gì lên board.")
        elif self.package.count() == 0:
            self.package_hint.setText("Không có gói phù hợp chip này. Chọn thư mục firmware khác.")
        else:
            self.package_hint.setText(
                "Chọn đúng mẫu board và GPIO. Nạp mới không đặt lại cấu hình cũ "
                "trừ khi chọn Xóa toàn bộ flash."
            )

    def _port_changed(self) -> None:
        """Never reuse a chip detection after selecting a different port."""
        self._chip = None
        self.flashed_port = None
        self.chip_label.setText("Chưa nhận diện chip cho cổng này.")
        self._fill_packages()

    def _refresh_ports(self) -> None:
        """Find newly plugged boards without reopening the dialog."""
        previous = self.ports.currentData()
        self.ports.blockSignals(True)
        self.ports.clear()
        for name, description, likely in available_ports():
            self.ports.addItem(f"{name} — {description}" + (" (ESP32?)" if likely else ""), name)
        index = self.ports.findData(previous)
        if index >= 0:
            self.ports.setCurrentIndex(index)
        self.ports.blockSignals(False)
        self._port_changed()

    def _set_busy(self, busy: bool) -> None:
        """Lock the entire workflow through writing and post-flash verification."""
        self._busy = busy
        for widget in (
            self.detect, self.close_button, self.ports, self.package, self.refresh,
            self.folder_button, self.update_mode, self.full_mode,
        ):
            widget.setEnabled(not busy)
        self.erase.setEnabled(not busy and self.full_mode.isChecked())
        self._update_flash_state()

    def _choose_folder(self) -> None:
        """Let the user point at another firmware folder."""
        folder = QFileDialog.getExistingDirectory(self, "Thư mục chứa gói firmware", str(self._folder))
        if folder:
            self._load_packages(Path(folder))

    # -- esptool runs -------------------------------------------------------------

    def _start(self, args: list[str]) -> None:
        """Free the port and run esptool in the background."""
        port = self.ports.currentData()
        self._release_port(port)
        self._set_busy(True)
        self._output = ""
        self._note("esptool " + " ".join(args))
        self._worker.start(args)

    def _detect(self) -> None:
        """Read the chip type so only matching firmware is offered."""
        if not self.ports.currentData():
            self._note("Chưa có cổng nào. Cắm board rồi mở lại hộp thoại này.")
            return
        self._target = None
        self.flashed_port = None
        self._chip = None
        self._start(detect_args(self.ports.currentData()))

    def _flash(self) -> None:
        """Verify the package files, then write them."""
        package = self.package.currentData()
        port = self.ports.currentData()
        if self._busy or package is None or not port:
            return
        if self._chip is None or package.chip != self._chip:
            self._note("Hãy nhận diện chip của cổng đang chọn trước khi nạp.")
            return
        if package.chip in NO_BLE_CHIPS:
            self._note("Chip này không có Bluetooth nên không làm bàn phím BLE được.")
            return
        try:
            package.verify()
        except (OSError, ValueError) as exc:
            self._note(str(exc))
            return
        full = self.full_mode.isChecked()
        erase = full and self.erase.isChecked()
        mode = "Nạp mới / Khôi phục" if full else "Cập nhật / Nạp đè"
        effect = (
            "XÓA TOÀN BỘ FLASH: mất tên, GPIO, profile và ghép đôi đã lưu trên board."
            if erase else "Không yêu cầu xóa cấu hình đã lưu trên board."
        )
        answer = QMessageBox.question(
            self, "Xác nhận nạp firmware",
            f"{mode} trên {port}\n{package.label}\n\n{effect}\n"
            "Board sẽ khởi động lại. Không rút cáp cho đến khi kiểm tra xong.\n"
            "Khi kết nối lại, app sẽ chép profile đang chọn vào board.\n\nTiếp tục?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.flashed_port = None
        self._target = package
        self._identity = identify_usb_device(port)
        self.progress.setValue(0)
        self._start(write_args(package, port, full=full, erase=erase))

    def _append(self, text: str) -> None:
        """Show esptool output and progress as it arrives."""
        self._output += text
        progress = parse_progress(text)
        if progress is not None:
            self.progress.setValue(progress)
        # esptool redraws progress with carriage returns; keep only finished lines.
        for line in text.replace("\r", "\n").split("\n"):
            if line.strip() and "%)" not in line:
                self.log.appendPlainText(line.rstrip())

    def _esptool_finished(self, code: int) -> None:
        """Report the run, then check the board when firmware was written."""
        if self._target is None:
            self._set_busy(False)
            self._detected(code)
            return
        if code != 0:
            self._note("Nạp thất bại. Kiểm tra cáp/cổng; nếu cần, giữ BOOT khi cắm board rồi thử lại.")
            self._set_busy(False)
            return
        self.progress.setValue(100)
        self._note("Đã ghi xong. Đang chờ board khởi động và trả lời…")
        self._attempt = 0
        self._verify_timer.start(1500)

    def _detected(self, code: int) -> None:
        """Filter packages by the chip esptool found."""
        chip = parse_chip(self._output) if code == 0 else None
        if chip is None:
            self.chip_label.setText("Không nhận diện được chip. Thử giữ nút BOOT khi cắm board.")
            self._chip = None
        else:
            self._chip = chip
            title = CHIP_TITLES.get(chip, chip)
            if chip in NO_BLE_CHIPS:
                self.chip_label.setText(
                    f"Chip: {title}. Chip này không có Bluetooth, nên không thể làm bàn phím "
                    "BLE; hiện chưa có firmware cho nó."
                )
            else:
                self.chip_label.setText(f"Chip: {title}.")
        self._fill_packages()
        if chip is not None and self.package.count() == 0 and chip not in NO_BLE_CHIPS:
            self._note(f"Chưa có gói firmware cho {CHIP_TITLES.get(chip, chip)} trong {self._folder}.")

    # -- check after writing ----------------------------------------------------------

    def _verify(self) -> None:
        """Retry until the board answers INFO with the chip and version just written."""
        package = self._target
        self._attempt += 1
        port = find_usb_port(self._identity) if self._identity else None
        port = port or self.ports.currentData()
        connection = Connection()
        try:
            connection.open(port)
            info = parse_info(connection.request("INFO", "INFO END", timeout=1.5))
        except (OSError, ValueError) as exc:
            if self._attempt < VERIFY_ATTEMPTS:
                self._verify_timer.start(VERIFY_INTERVAL_MS)
            else:
                self._note(f"Board chưa trả lời sau khi nạp ({exc}). Rút ra cắm lại rồi bấm Kết nối.")
                self._set_busy(False)
            return
        finally:
            connection.close()
        self._set_busy(False)
        if info.chip != package.chip or info.firmware != package.version:
            self._note(
                f"Board trả lời nhưng chạy {info.chip} firmware {info.firmware}, "
                f"không khớp gói {package.chip} {package.version}."
            )
            return
        self.flashed_port = port
        self._note(f"Thành công: {info.title}. GPIO {','.join(map(str, info.config.pins))}.")

    def _note(self, text: str) -> None:
        """Append an app message (not esptool output) to the log."""
        self.log.appendPlainText("» " + text)

    def reject(self) -> None:
        """Refuse to close while esptool is writing."""
        if self._busy:
            self._note("Đang nạp; hãy đợi xong rồi đóng.")
            return
        self._verify_timer.stop()
        super().reject()
