"""Prebuilt firmware packages and the esptool runs that write them.

A package is one folder made by ``build-firmware.ps1``::

    dist/firmware/ti-clicker/
        manifest.json
        bootloader.bin  partitions.bin  boot_app0.bin  firmware.bin

``manifest.json`` names the target chip and the flash offset of every file. An update
writes only ``firmware.bin``, so the NVS partition (profile, name, wiring) is kept.
"""

import contextlib
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import esptool

from .device import CHIP_TITLES, chip_key

SCHEMA = 1
MAX_IMAGE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True)
class Image:
    """One file written at one flash offset."""

    offset: int
    path: Path
    sha256: str


@dataclass(frozen=True)
class Package:
    """Firmware for one board template on one chip."""

    folder: Path
    board: str
    title: str
    chip: str
    version: str
    pins: tuple[int, ...]
    app: Image
    full: tuple[Image, ...]

    @property
    def label(self) -> str:
        """Text for the package list, e.g. ``Ti Clicker · ESP32-C3 · 3 nút · v0.11.0``."""
        chip = CHIP_TITLES.get(self.chip, self.chip)
        pins = ",".join(str(pin) for pin in self.pins)
        return f"{self.title} · {chip} · {len(self.pins)} nút (GPIO {pins}) · v{self.version}"

    def verify(self) -> None:
        """Check every file against the manifest before anything is written.

        Raises:
            ValueError: If a file is missing, too large or does not match its hash.
        """
        for image in {self.app, *self.full}:
            if not image.path.is_file():
                raise ValueError(f"Thiếu file {image.path.name} trong gói {self.board}.")
            data = image.path.read_bytes()
            if not data or len(data) > MAX_IMAGE_BYTES:
                raise ValueError(f"File {image.path.name} rỗng hoặc quá lớn.")
            if hashlib.sha256(data).hexdigest() != image.sha256:
                raise ValueError(f"File {image.path.name} không khớp SHA-256; hãy build lại gói.")


def _image(folder: Path, entry: dict) -> Image:
    """Read one manifest entry, refusing paths that leave the package folder."""
    path = (folder / str(entry["file"])).resolve()
    if path.parent != folder.resolve():
        raise ValueError(f"Đường dẫn file không hợp lệ: {entry['file']!r}")
    offset = int(str(entry["offset"]), 0)
    if not 0 <= offset < MAX_IMAGE_BYTES:
        raise ValueError(f"Địa chỉ ghi không hợp lệ: {entry['offset']!r}")
    sha = str(entry["sha256"]).lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise ValueError(f"SHA-256 không hợp lệ cho {entry['file']!r}")
    return Image(offset, path, sha)


def load_package(manifest: Path) -> Package:
    """Parse one ``manifest.json``.

    Raises:
        ValueError: If the manifest is malformed or unsupported.
        OSError: If it cannot be read.
    """
    try:
        data = json.loads(manifest.read_text(encoding="utf-8-sig"))
        if data["schema"] != SCHEMA:
            raise ValueError(f"Manifest schema {data['schema']} chưa được hỗ trợ.")
        folder = manifest.parent
        chip = chip_key(str(data["chip"]))
        if chip not in CHIP_TITLES:
            raise ValueError(f"Chip không hỗ trợ: {data['chip']!r}")
        return Package(
            folder,
            str(data["board"]),
            str(data["title"]),
            chip,
            str(data["version"]),
            tuple(int(pin) for pin in data["pins"]),
            _image(folder, data["app"]),
            tuple(_image(folder, entry) for entry in data["full"]),
        )
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{manifest}: manifest không hợp lệ ({exc}).") from exc


def default_firmware_dir() -> Path:
    """``firmware`` next to the packaged EXE, or ``dist/firmware`` in the source tree."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "firmware"
    return Path(__file__).resolve().parents[2] / "dist" / "firmware"


def find_packages(folder: Path) -> tuple[list[Package], list[str]]:
    """Load every package below ``folder``.

    Returns:
        Valid packages sorted by chip and title, and one message per invalid manifest.
    """
    packages, errors = [], []
    for manifest in sorted(folder.glob("*/manifest.json")):
        try:
            packages.append(load_package(manifest))
        except (OSError, ValueError) as exc:
            errors.append(str(exc))
    packages.sort(key=lambda package: (package.chip, package.title))
    return packages, errors


def write_args(package: Package, port: str, *, full: bool, erase: bool) -> list[str]:
    """esptool arguments for an update (app only) or a full first-time install.

    ``--chip`` makes esptool refuse a board whose chip does not match the package.
    """
    images = package.full if full else (package.app,)
    args = ["--chip", package.chip, "--port", port, "--baud", "460800"]
    args += ["--before", "default_reset", "--after", "hard_reset", "write_flash"]
    if full and erase:
        args.append("--erase-all")
    for image in images:
        args += [hex(image.offset), str(image.path)]
    return args


def detect_args(port: str) -> list[str]:
    """esptool arguments that only read the chip type."""
    return ["--port", port, "--before", "default_reset", "--after", "hard_reset", "chip_id"]


def parse_chip(output: str) -> str | None:
    """Find the chip esptool detected, as a key such as ``esp32c3``."""
    found = re.findall(r"Detecting chip type\.\.\. (ESP32(?:-[A-Z0-9]+)?)\b", output)
    return chip_key(found[-1]) if found else None


def parse_progress(output: str) -> int | None:
    """Last ``(NN %)`` progress value esptool printed."""
    found = re.findall(r"\((\d{1,3}) ?%\)", output)
    return min(int(found[-1]), 100) if found else None


def run_esptool(args: list[str], write) -> int:
    """Run esptool in this process, sending its output to ``write``.

    Runs on a worker thread; the GUI never imports or prints to stdout itself, so
    redirecting the process-wide streams for the duration is safe.

    Returns:
        0 on success, nonzero on failure.
    """

    class Stream:
        def write(self, text: str) -> int:
            write(text)
            return len(text)

        def flush(self) -> None:
            pass

    stream = Stream()
    with contextlib.redirect_stdout(stream), contextlib.redirect_stderr(stream):
        try:
            esptool.main(args)
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
        # esptool can also raise StopIteration, struct.error, ... when the chip stops
        # answering; any escape would leave the dialog stuck as busy.
        except Exception as exc:  # noqa: BLE001
            write(f"\nLỗi: {exc}\n")
            return 1
    return 0
