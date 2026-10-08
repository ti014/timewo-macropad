"""Validated macro profiles and atomic JSON persistence.

No actions execute while loading configuration. Unknown schemas fail closed.
"""

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

KINDS = {
    "lock_screen": "Khóa màn hình",
    "sequence": "Chu\u1ed7i ph\u00edm",
    "screenshot": "Ch\u1ee5p m\u00e0n h\u00ecnh v\u00e0o clipboard",
    "close_app": "\u0110\u00f3ng \u1ee9ng d\u1ee5ng \u0111ang d\u00f9ng",
    "none": "Không gán",
    "hotkey": "Phím tắt",
    "text": "Văn bản",
    "app": "Mở ứng dụng",
    "url": "Mở website",
}
FIRMWARE_KIND_IDS = {
    "none": 0,
    "hotkey": 1,
    "text": 2,
    "sequence": 3,
    "lock_screen": 4,
    "screenshot": 5,
    "close_app": 6,
    "app": 7,
    "url": 8,
}
FIRMWARE_DIRECT_KINDS = {"none", "hotkey", "text", "sequence", "lock_screen", "close_app"}
ALIASES = {
    "control": "ctrl",
    "win": "cmd",
    "windows": "cmd",
    "esc": "esc",
    "escape": "esc",
    "return": "enter",
    "del": "delete",
    "spacebar": "space",
    "pageup": "page_up",
    "pagedown": "page_down",
    "plus": "+",
}
SPECIAL = {
    "ctrl",
    "alt",
    "shift",
    "cmd",
    "enter",
    "tab",
    "space",
    "backspace",
    "delete",
    "insert",
    "home",
    "end",
    "page_up",
    "page_down",
    "up",
    "down",
    "left",
    "right",
    "esc",
    "caps_lock",
    "print_screen",
    "media_volume_up",
    "media_volume_down",
    "media_volume_mute",
    "media_play_pause",
    "media_next",
    "media_previous",
} | {f"f{i}" for i in range(1, 25)}


def parse_hotkey(value: str) -> list[str]:
    """Validate a single chord, such as Ctrl+Shift+S.

    Args:
        value: Keys separated by plus signs; use 'plus' for a literal plus.

    Returns:
        Normalized key names, with modifiers before the ordinary key.

    Raises:
        ValueError: If the chord contains invalid, repeated or multiple ordinary keys.
    """
    keys = [ALIASES.get(key.strip().lower(), key.strip().lower()) for key in value.split("+")]
    modifiers = {"ctrl", "alt", "shift", "cmd"}
    if not 1 <= len(keys) <= 5 or len(set(keys)) != len(keys):
        raise ValueError("Phím tắt không hợp lệ hoặc bị lặp phím.")
    for key in keys:
        if key not in SPECIAL and not (len(key) == 1 and key.isascii() and key.isprintable()):
            raise ValueError(f"Không nhận ra phím '{key}'. Ví dụ đúng: Ctrl+Shift+S hoặc F5.")
    if sum(key not in modifiers for key in keys) != 1:
        if sum(key not in modifiers for key in keys) > 1:
            raise ValueError("Use Chuoi phim with commas for sequential keys, for example: 1,Enter.")
        raise ValueError("Chọn một phím chính, có thể kèm Ctrl / Alt / Shift / Win.")
    return [key for key in keys if key in modifiers] + [key for key in keys if key not in modifiers]


def parse_sequence(value: str) -> list[list[str]]:
    """Validate a sequence of chords, such as ``1,Enter`` or ``Ctrl+C,Enter``."""
    parts = [part.strip() for part in value.split(",")]
    if not 1 <= len(parts) <= 32 or any(not part for part in parts):
        raise ValueError("A key sequence needs 1 to 32 steps separated by commas.")
    return [parse_hotkey(part) for part in parts]


@dataclass(frozen=True)
class Action:
    """One button assignment.

    Attributes:
        kind: One of the supported action identifiers.
        value: Shortcut, literal text, absolute executable path or web URL.
    """

    kind: str = "none"
    value: str = ""

    def validate(self) -> None:
        """Reject invalid actions without executing them.

        Raises:
            ValueError: If the kind, size, shortcut, URL or path is invalid.
        """
        if not isinstance(self.kind, str) or self.kind not in KINDS:
            raise ValueError("Loại macro không được hỗ trợ.")
        if not isinstance(self.value, str) or len(self.value) > 2000 or "\0" in self.value:
            raise ValueError("Giá trị phải là văn bản tối đa 2000 ký tự, không chứa NUL.")
        if self.kind == "hotkey":
            parse_hotkey(self.value)
        elif self.kind == "sequence":
            parse_sequence(self.value)
        elif self.kind == "text" and not self.value:
            raise ValueError("Hãy nhập văn bản cần gửi.")
        elif self.kind == "url":
            url = urlsplit(self.value)
            if (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or any(char.isspace() for char in self.value)
            ):
                raise ValueError(
                    "Website phải bắt đầu bằng https:// hoặc http://, không có khoảng trắng."
                )
        elif self.kind == "app":
            path = Path(self.value)
            if not path.is_absolute() or path.suffix.lower() != ".exe":
                raise ValueError(
                    "Hãy chọn đường dẫn đầy đủ tới file .exe; không nhập lệnh terminal."
                )


@dataclass
class Config:
    """Saved profiles; armed state is deliberately never persisted.

    Attributes:
        active: Selected profile name.
        profiles: Named lists of exactly four actions.
    """

    active: str = "Mặc định"
    profiles: dict[str, list[Action]] = field(
        default_factory=lambda: {
            "Mặc định": [Action("hotkey", key) for key in ("Ctrl+C", "Ctrl+V", "Alt+Tab", "Ctrl+S")]
        }
    )

    def validate(self) -> None:
        """Validate all profiles before they become executable.

        Raises:
            ValueError: If a name or profile mapping is invalid.
        """
        if not isinstance(self.active, str) or self.active not in self.profiles:
            raise ValueError("Profile đang chọn không tồn tại.")
        if not 1 <= len(self.profiles) <= 50:
            raise ValueError("Chỉ hỗ trợ từ 1 đến 50 profile.")
        for name, actions in self.profiles.items():
            if not isinstance(name, str) or not name.strip() or len(name) > 60:
                raise ValueError("Tên profile phải dài từ 1 đến 60 ký tự.")
            if len(actions) != 4:
                raise ValueError("Mỗi profile phải có đúng 4 nút.")
            for action in actions:
                action.validate()


def load_config(path: Path) -> Config:
    """Read settings, using defaults only when the file does not exist.

    Args:
        path: Configuration file path.

    Returns:
        Fully validated settings.

    Raises:
        ValueError: If existing data is malformed or unsupported.
        OSError: If the file cannot be read.
    """
    if not path.exists():
        return Config()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or raw.get("version") != 1:
            raise ValueError("Phiên bản cấu hình không hợp lệ.")
        config = Config(
            raw["active"],
            {
                name: [Action(**action) for action in actions]
                for name, actions in raw["profiles"].items()
            },
        )
        config.validate()
        return config
    except (TypeError, KeyError, AttributeError, json.JSONDecodeError) as exc:
        raise ValueError("File cấu hình bị lỗi. File gốc được giữ nguyên.") from exc


def save_config(path: Path, config: Config) -> None:
    """Atomically replace settings after complete validation.

    Args:
        path: Destination settings file.
        config: Profiles to persist.

    Raises:
        ValueError: If configuration is invalid.
        OSError: If storage is unavailable; previous settings remain intact.
    """
    config.validate()
    payload = {
        "version": 1,
        "active": config.active,
        "profiles": {
            name: [asdict(action) for action in actions]
            for name, actions in config.profiles.items()
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as handle:
            temp_path = Path(handle.name)
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
