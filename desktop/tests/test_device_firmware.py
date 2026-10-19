"""Board info/config protocol, firmware packages, scripts and wait steps."""

import hashlib
import json
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import serial

from macropad.actions import Executor, script_command
from macropad.config import Action, parse_sequence
from macropad.device import DeviceConfig, parse_actions, parse_info
from macropad.firmware import (
    detect_args,
    find_packages,
    load_package,
    parse_chip,
    parse_progress,
    write_args,
)
from macropad.protocol import Decoder
from macropad.transport import Connection

INFO = [
    "DEVICE 1 esp32c3 0.11.0 ti-clicker",
    "CAPS ble_hid hotkey sequence wait media lock_screen close_app",
    "LIMITS 4 512 15 5 200 500 10000",
    "PINS_OK 0,1,2,3,4,5,6,7,8,9,10,20,21",
    "CONFIG 546920436C69636B6572 7,8,9 30 2500",
    "INFO END",
]


class FakeSerial:
    """Answers each written command with canned lines, like the firmware would."""

    def __init__(self, answers: dict[str, bytes]) -> None:
        self.answers = answers
        self.buffer = b""
        self.written: list[bytes] = []
        self.is_open = True

    @property
    def in_waiting(self) -> int:
        return len(self.buffer)

    def read(self, size: int) -> bytes:
        data, self.buffer = self.buffer[:size], self.buffer[size:]
        return data

    def write(self, data: bytes) -> int:
        self.written.append(data)
        self.buffer += self.answers.get(data.decode().split()[0], b"")
        return len(data)

    def reset_input_buffer(self) -> None:
        self.buffer = b""

    def open(self) -> None:
        pass

    def close(self) -> None:
        self.is_open = False

    def flush(self) -> None:
        pass


def open_fake(answers: dict[str, bytes]) -> tuple[Connection, FakeSerial]:
    fake = FakeSerial(answers)
    connection = Connection()
    with patch("macropad.transport.serial.Serial", return_value=fake):
        connection.open("COM9")
    return connection, fake


def test_device_config_roundtrip_keeps_vietnamese_name() -> None:
    """The name travels as UTF-8 hex, so spaces and diacritics survive."""
    config = DeviceConfig("Remote Phương", (7, 8, 9), 30, 2500)
    command = config.command()
    assert command.startswith("CFG ") and " 7,8,9 30 2500" in command
    echoed = "CONFIG " + command.split(maxsplit=1)[1]
    assert DeviceConfig.parse(echoed) == config


def test_parse_info_and_validate() -> None:
    """INFO lines become a DeviceInfo that rejects what the firmware would."""
    info = parse_info(INFO)
    assert info.chip == "esp32c3" and info.firmware == "0.11.0" and info.board == "ti-clicker"
    assert info.config == DeviceConfig("Ti Clicker", (7, 8, 9), 30, 2500)
    assert "wait" in info.caps and info.title == "Ti Clicker · ESP32-C3 · firmware 0.11.0"
    info.validate(DeviceConfig("Remote Phuong", (7, 8, 10), 30, 2500))
    with pytest.raises(ValueError, match="GPIO 18"):
        info.validate(DeviceConfig("x", (18,), 30, 2500))  # native USB D- on the C3
    with pytest.raises(ValueError, match="khác nhau"):
        info.validate(DeviceConfig("x", (7, 7), 30, 2500))
    with pytest.raises(ValueError, match="byte"):
        info.validate(DeviceConfig("Điều khiển Phương", (7,), 30, 2500))  # > 15 UTF-8 bytes
    with pytest.raises(ValueError, match="Debounce"):
        info.validate(DeviceConfig("x", (7,), 1, 2500))
    with pytest.raises(ValueError, match="không đầy đủ"):
        parse_info(INFO[1:])


def test_parse_actions() -> None:
    """DUMP lines decode to kind id and value per button."""
    lines = ["ACT 1 1 4374726C2B43", "ACT 2 7 -", "DUMP END"]
    assert parse_actions(lines) == {1: (1, "Ctrl+C"), 2: (7, "")}


def test_decoder_keeps_replies_and_reads_new_header() -> None:
    """Replies are captured, never reported as presses; 0.11 header works on any chip."""
    decoder = Decoder()
    assert decoder.feed("\n".join(INFO).encode() + b"\n") == []
    assert decoder.replies == INFO
    decoder.feed(b"ESP32 macropad: 2-button test ready.\n")
    decoder.feed(b"BTN1 GPIO25 RELEASED count=0\nBTN2 GPIO26 RELEASED count=0\n")
    assert decoder.pins == {1: 25, 2: 26} and decoder.status_count == 1


def test_request_returns_reply_and_keeps_presses_for_poll() -> None:
    """A press that arrives during a request is not lost."""
    reply = b"BTN2 GPIO4 PRESSED count=1\n" + "\n".join(INFO).encode() + b"\n"
    connection, fake = open_fake({"INFO": reply})
    assert connection.request("INFO", "INFO END") == INFO
    assert fake.written[-1] == b"INFO\n"
    assert connection.poll() == [2]


def test_request_times_out() -> None:
    """Old firmware never answers INFO; that is an error, not a hang."""
    connection, _ = open_fake({})
    with pytest.raises(serial.SerialException):
        connection.request("INFO", "INFO END", timeout=0.05)


def test_sequence_wait_steps() -> None:
    """wait:<ms> is a delay step, bounded like the firmware."""
    assert parse_sequence("Ctrl+L, wait:300, Ctrl+C") == [["ctrl", "l"], 300, ["ctrl", "c"]]
    assert parse_sequence("A,WAIT:100") == [["a"], 100]
    for bad in ("wait:5000", "wait:abc", "wait:100", "A,wait:2000,B,wait:2000"):
        with pytest.raises(ValueError):
            parse_sequence(bad)
    keyboard = Mock()
    with patch("macropad.actions.time.sleep") as sleep:
        Executor(keyboard).execute(Action("sequence", "A,wait:250,B"))
    sleep.assert_called_once_with(0.25)
    assert [call.args[0] for call in keyboard.press.call_args_list] == ["a", "b"]


def test_script_action(tmp_path: Path) -> None:
    """Scripts run with the right interpreter and no shell string."""
    with pytest.raises(ValueError):
        Action("script", "report.py").validate()
    with pytest.raises(ValueError):
        Action("script", str(tmp_path / "x.exe")).validate()
    ps1 = tmp_path / "report.ps1"
    ps1.write_text("Write-Host hi", encoding="utf-8")
    assert script_command(ps1)[:2] == ["powershell.exe", "-NoProfile"]
    assert script_command(tmp_path / "a.cmd") == ["cmd.exe", "/c", str(tmp_path / "a.cmd")]
    with patch("macropad.actions.shutil.which", return_value=None), pytest.raises(OSError):
        script_command(tmp_path / "a.py")
    with patch("macropad.actions.subprocess.Popen") as popen:
        Executor(Mock()).execute(Action("script", str(ps1)))
    assert popen.call_args.kwargs["shell"] is False
    with pytest.raises(FileNotFoundError):
        Executor(Mock()).execute(Action("script", str(tmp_path / "missing.bat")))


def make_package(folder: Path, chip: str = "esp32c3", file: str = "firmware.bin") -> Path:
    """Write a small package with correct hashes."""
    folder.mkdir(parents=True)
    entries = []
    for name, offset in (("bootloader.bin", "0x0"), ("partitions.bin", "0x8000"),
                         ("boot_app0.bin", "0xe000"), ("firmware.bin", "0x10000")):
        data = name.encode() * 4
        (folder / name).write_bytes(data)
        entries.append({"file": name, "offset": offset, "sha256": hashlib.sha256(data).hexdigest()})
    app = dict(entries[-1], file=file)
    manifest = {
        "schema": 1, "board": "ti-clicker", "title": "Ti Clicker", "chip": chip,
        "version": "0.11.0", "pins": [7, 8, 9], "app": app, "full": entries,
    }
    path = folder / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


def test_package_load_verify_and_args(tmp_path: Path) -> None:
    """Update writes only the app, so NVS survives; full writes all four images."""
    package = load_package(make_package(tmp_path / "ti-clicker"))
    package.verify()
    assert "Ti Clicker · ESP32-C3 · 3 nút (GPIO 7,8,9)" in package.label
    update = write_args(package, "COM9", full=False, erase=False)
    assert update[:2] == ["--chip", "esp32c3"] and update.count("0x") == 0
    assert update[-2:] == ["0x10000", str(package.app.path)]
    full = write_args(package, "COM9", full=True, erase=True)
    assert "--erase-all" in full and ["0x0", "0x8000", "0xe000", "0x10000"] == [
        arg for arg in full if arg.startswith("0x")
    ]
    assert "--erase-all" not in write_args(package, "COM9", full=False, erase=True)
    (tmp_path / "ti-clicker" / "firmware.bin").write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        package.verify()


def test_package_rejects_escaping_path_and_bad_chip(tmp_path: Path) -> None:
    """A manifest cannot point outside its folder or name an unknown chip."""
    with pytest.raises(ValueError, match="không hợp lệ"):
        load_package(make_package(tmp_path / "a", file="../evil.bin"))
    with pytest.raises(ValueError, match="Chip"):
        load_package(make_package(tmp_path / "b", chip="esp8266"))
    packages, errors = find_packages(tmp_path)
    assert packages == [] and len(errors) == 2


def test_esptool_output_parsing() -> None:
    """Chip and progress come from esptool's own text."""
    assert detect_args("COM9")[-1] == "chip_id"
    assert parse_chip("Connecting....\nDetecting chip type... ESP32-C3\nChip is ESP32-C3") == "esp32c3"
    assert parse_chip("Detecting chip type... ESP32\nChip is ESP32-D0WD-V3") == "esp32"
    assert parse_chip("Detecting chip type... ESP32-S2\n") == "esp32s2"
    assert parse_chip("A fatal error occurred: Failed to connect") is None
    assert parse_progress("Writing at 0x00010000... (3 %)\rWriting at 0x00020000... (47 %)") == 47


def test_uart_bridge_keeps_dtr_low() -> None:
    """On CP210x/CH340 boards DTR drives IO0; holding it low avoids download mode."""
    fake = FakeSerial({})
    bridge = Mock(device="COM7", vid=0x10C4)
    with patch("macropad.transport.serial.Serial", return_value=fake), patch(
        "macropad.transport.list_ports.comports", return_value=[bridge]
    ):
        Connection().open("COM7")
    assert fake.dtr is False


def test_esptool_crash_still_reports_failure() -> None:
    """Any esptool exception ends the run with a failure code instead of escaping."""
    from macropad.firmware import run_esptool

    out: list[str] = []
    with patch("macropad.firmware.esptool.main", side_effect=StopIteration):
        assert run_esptool(["chip_id"], out.append) == 1
