"""Launch the Windows macropad application with a single-instance guard."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QLockFile, QStandardPaths, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox

from macropad.ui import MainWindow


def main() -> int:
    """Run the GUI without connecting to devices or arming automatically.

    Returns:
        Process exit code; nonzero on invalid settings or startup failure.
    """
    app = QApplication(sys.argv)
    app.setApplicationName("MacropadConfigurator")
    app.setOrganizationName("Macropad")
    app.setStyle("Fusion")
    smoke = "--smoke-test" in sys.argv
    settings_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppLocalDataLocation))
    try:
        settings_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        QMessageBox.critical(None, "Không mở được ứng dụng", str(exc))
        return 1
    lock = QLockFile(str(settings_dir / "application.lock"))
    if not smoke and not lock.tryLock(100):
        QMessageBox.information(
            None,
            "Ứng dụng đang chạy",
            "Mở Macropad Configurator từ thanh taskbar hoặc khay hệ thống.",
        )
        return 0
    if not smoke:
        try:
            handler = RotatingFileHandler(
                settings_dir / "connection.log", maxBytes=500_000, backupCount=2, encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
            logger = logging.getLogger("macropad")
            logger.setLevel(logging.INFO)
            logger.addHandler(handler)
            logger.info("Starting timewo-macropad v0.10")
        except OSError as exc:
            QMessageBox.warning(None, "Không ghi được log", str(exc))
    try:
        window = MainWindow(settings_dir / "profiles.json", testing=smoke)
    except (OSError, ValueError) as exc:
        QMessageBox.critical(
            None, "Cấu hình không đọc được", f"{exc}\nFile được giữ nguyên tại:\n{settings_dir}"
        )
        return 1
    window.show()
    if smoke:
        QTimer.singleShot(300, window.close)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
