"""What a connected board reports about itself, and its editable settings.

Firmware 0.11+ answers ``INFO`` with::

    DEVICE 1 esp32c3 0.11.0 ti-clicker
    CAPS ble_hid hotkey sequence wait media lock_screen close_app
    LIMITS <max buttons> <max value bytes> <max name bytes> <debounce min> <max> <hold min> <max>
    PINS_OK 0,1,2,...
    CONFIG <name hex> <pin,pin,...> <debounce ms> <hold ms>
    INFO END
"""

from dataclasses import dataclass

# esptool and the firmware name chips differently ("ESP32-C3" vs "esp32c3").
CHIP_TITLES = {
    "esp32": "ESP32",
    "esp32s2": "ESP32-S2",
    "esp32s3": "ESP32-S3",
    "esp32c3": "ESP32-C3",
    "esp32c6": "ESP32-C6",
    "esp32h2": "ESP32-H2",
}
# Chips without Bluetooth LE can never act as a BLE keyboard.
NO_BLE_CHIPS = {"esp32s2"}


def chip_key(name: str) -> str:
    """Normalize ``ESP32-C3`` / ``esp32c3`` to ``esp32c3``."""
    return name.strip().lower().replace("-", "").replace("_", "")


@dataclass(frozen=True)
class DeviceConfig:
    """Settings the board stores in NVS and applies at boot."""

    name: str
    pins: tuple[int, ...]
    debounce_ms: int
    hold_ms: int

    def command(self) -> str:
        """Encode as the firmware ``CFG`` command; the name travels as hex."""
        name = self.name.encode("utf-8").hex().upper()
        pins = ",".join(str(pin) for pin in self.pins)
        return f"CFG {name} {pins} {self.debounce_ms} {self.hold_ms}"

    @classmethod
    def parse(cls, line: str) -> "DeviceConfig":
        """Decode one ``CONFIG`` line.

        Raises:
            ValueError: If the line is malformed.
        """
        fields = line.split()
        if len(fields) != 5 or fields[0] != "CONFIG":
            raise ValueError(f"Dòng CONFIG không hợp lệ: {line!r}")
        name = "" if fields[1] == "-" else bytes.fromhex(fields[1]).decode("utf-8")
        pins = tuple(int(pin) for pin in fields[2].split(","))
        return cls(name, pins, int(fields[3]), int(fields[4]))


@dataclass(frozen=True)
class Limits:
    """Firmware bounds the settings dialog must respect."""

    max_buttons: int = 4
    max_value: int = 512
    max_name: int = 15
    debounce: tuple[int, int] = (5, 200)
    hold: tuple[int, int] = (500, 10000)


@dataclass(frozen=True)
class DeviceInfo:
    """Identity, capabilities and current settings of one board."""

    chip: str
    firmware: str
    board: str
    caps: frozenset[str]
    limits: Limits
    usable_pins: tuple[int, ...]
    config: DeviceConfig

    @property
    def title(self) -> str:
        """Short human description, e.g. ``Ti Clicker · ESP32-C3 · firmware 0.11.0``."""
        chip = CHIP_TITLES.get(self.chip, self.chip)
        return f"{self.config.name} · {chip} · firmware {self.firmware}"

    def validate(self, config: DeviceConfig) -> None:
        """Mirror the firmware checks so the user sees the reason before writing.

        Raises:
            ValueError: If the board would reject these settings.
        """
        raw = config.name.encode("utf-8")
        if not raw or len(raw) > self.limits.max_name:
            raise ValueError(f"Tên phải dài 1–{self.limits.max_name} byte (chữ có dấu tính 2–3 byte).")
        if any(ord(char) < 0x20 or ord(char) == 0x7F for char in config.name):
            raise ValueError("Tên không được chứa ký tự điều khiển.")
        if not 1 <= len(config.pins) <= self.limits.max_buttons:
            raise ValueError(f"Số nút phải từ 1 đến {self.limits.max_buttons}.")
        if len(set(config.pins)) != len(config.pins):
            raise ValueError("Mỗi nút phải dùng một GPIO khác nhau.")
        bad = [pin for pin in config.pins if pin not in self.usable_pins]
        if bad:
            raise ValueError(f"GPIO {bad[0]} không dùng được cho nút trên chip này.")
        low, high = self.limits.debounce
        if not low <= config.debounce_ms <= high:
            raise ValueError(f"Debounce phải từ {low} đến {high} ms.")
        low, high = self.limits.hold
        if not low <= config.hold_ms <= high:
            raise ValueError(f"Thời gian giữ phải từ {low} đến {high} ms.")


def parse_info(lines: list[str]) -> DeviceInfo:
    """Build a DeviceInfo from the reply lines of one ``INFO`` request.

    Raises:
        ValueError: If a required line is missing or malformed.
    """
    by_verb = {line.split()[0]: line.split()[1:] for line in lines if line.split()}
    try:
        _version, chip, firmware, board = by_verb["DEVICE"]
        numbers = [int(value) for value in by_verb["LIMITS"]]
        limits = Limits(
            numbers[0], numbers[1], numbers[2], (numbers[3], numbers[4]), (numbers[5], numbers[6])
        )
        pins = tuple(int(pin) for pin in by_verb["PINS_OK"][0].split(","))
        config_line = next(line for line in lines if line.startswith("CONFIG "))
        return DeviceInfo(
            chip_key(chip),
            firmware,
            board,
            frozenset(by_verb.get("CAPS", [])),
            limits,
            pins,
            DeviceConfig.parse(config_line),
        )
    except (KeyError, IndexError, ValueError, StopIteration) as exc:
        raise ValueError(f"Board trả lời INFO không đầy đủ: {exc}") from exc


def parse_actions(lines: list[str]) -> dict[int, tuple[int, str]]:
    """Decode ``ACT <n> <kind> <hex|->`` lines into ``{button: (kind id, value)}``.

    Raises:
        ValueError: If a line is malformed.
    """
    actions = {}
    for line in lines:
        fields = line.split()
        if len(fields) != 4 or fields[0] != "ACT":
            continue
        value = "" if fields[3] == "-" else bytes.fromhex(fields[3]).decode("utf-8")
        actions[int(fields[1])] = (int(fields[2]), value)
    return actions
