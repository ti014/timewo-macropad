"""Tests for persistence, validation and the existing firmware protocol."""

import json
from pathlib import Path

import pytest

from macropad.config import (
    FIRMWARE_DIRECT_KINDS,
    Action,
    Config,
    load_config,
    parse_hotkey,
    parse_sequence,
    save_config,
)
from macropad.protocol import Decoder


def test_config_roundtrip(tmp_path: Path) -> None:
    """Persist Unicode and isolated profiles without altering defaults."""
    path = tmp_path / "settings.json"
    config = Config()
    config.profiles["Tiếng Việt"] = [Action("text", "Xin chào")] * 4
    config.active = "Tiếng Việt"
    save_config(path, config)
    assert load_config(path) == config
    assert load_config(tmp_path / "missing.json").active == "Mặc định"


@pytest.mark.parametrize("raw", ["[]", "{}", "null", '{"version": 99}', "broken"])
def test_bad_config_is_not_overwritten(tmp_path: Path, raw: str) -> None:
    """Malformed user data fails explicitly and remains recoverable."""
    path = tmp_path / "bad.json"
    path.write_text(raw, encoding="utf-8")
    with pytest.raises(ValueError):
        load_config(path)
    assert path.read_text(encoding="utf-8") == raw


@pytest.mark.parametrize(
    "kind,value",
    [
        ("hotkey", "Ctrl++C"),
        ("hotkey", "Ctrl+Ctrl+C"),
        ("hotkey", "Ctrl+unknown"),
        ("url", "javascript:alert(1)"),
        ("url", "file:///C:/x"),
        ("app", "C:/x.bat"),
        ("text", "x" * 2001),
        ("shell", "whoami"),
    ],
)
def test_reject_invalid_action(kind: str, value: str) -> None:
    """Reject unsupported keys, URLs, scripts and oversized text."""
    with pytest.raises(ValueError):
        Action(kind, value).validate()


def test_hotkey_aliases() -> None:
    """Normalize common names for deterministic keyboard execution."""
    assert parse_hotkey(" CTRL + ALT + Delete ") == ["ctrl", "alt", "delete"]
    assert parse_hotkey("Win+Shift+S") == ["cmd", "shift", "s"]
    assert parse_hotkey("F24") == ["f24"]


def test_key_sequence_uses_comma_between_steps() -> None:
    """A sequence can send separate primary keys in order."""
    assert parse_sequence("1,Enter") == [["1"], ["enter"]]
    Action("sequence", "1,Enter").validate()
    with pytest.raises(ValueError):
        Action("hotkey", "1+Enter").validate()


def test_launch_and_text_actions_require_companion_app() -> None:
    """Standalone HID never types paths or Unicode through the active IME."""
    assert not {"app", "url", "text"} & FIRMWARE_DIRECT_KINDS


def test_decoder_chunks_release_and_duplicates() -> None:
    """Emit once per press even with split serial packets and repeated lines."""
    decoder = Decoder()
    assert decoder.feed(b"BTN1 GPIO3 PRE") == []
    assert decoder.feed(b"SSED count=1\r\n") == [1]
    assert decoder.feed(b"BTN1 GPIO3 PRESSED count=1\n") == []
    assert decoder.feed(b"BTN1 GPIO3 RELEASED count=1\n") == []
    assert decoder.feed(b"BTN1 GPIO3 PRESSED count=2\n") == [1]
    assert decoder.feed(b"BTN4 GPIO6 PRESSED count=1\n") == [4]
    assert decoder.feed(b"BTN1 GPIO99 PRESSED count=3\nnoise\n") == []


def test_status_snapshot_never_executes_macro() -> None:
    """Ignore pressed status at reconnect and after the '?' command."""
    decoder = Decoder()
    assert (
        decoder.feed(
            b"ESP32-C3 macropad: 4-button test ready.\n"
            b"Wire each button between GPIO and GND. LOW = pressed.\n"
            b"Send '?' to show current state and press counts.\n"
            b"BTN1 GPIO3 PRESSED count=8\nBTN2 GPIO4 RELEASED count=2\n"
            b"BTN3 GPIO5 RELEASED count=1\nBTN4 GPIO6 RELEASED count=0\n"
        )
        == []
    )
    assert decoder.feed(b"BTN1 GPIO3 PRESSED count=8\n") == []
    assert decoder.feed(b"BTN1 GPIO3 RELEASED count=8\nBTN1 GPIO3 PRESSED count=9\n") == [1]


def test_decoder_bounded_buffer() -> None:
    """Discard overlong garbage without interpreting its suffix as a macro."""
    decoder = Decoder()
    assert decoder.feed(b"x" * 9000) == []
    assert decoder.feed(b"BTN1 GPIO3 PRESSED count=1\n") == []
    assert decoder.feed(b"BTN2 GPIO4 PRESSED count=1\n") == [2]


def test_config_wrong_profile_size(tmp_path: Path) -> None:
    """A profile must map exactly four physical buttons."""
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"version": 1, "active": "X", "profiles": {"X": []}}))
    with pytest.raises(ValueError):
        load_config(path)


def test_partial_press_before_arming_is_discarded() -> None:
    """A stale partial packet must not execute after macro activation."""
    decoder = Decoder()
    assert decoder.feed(b"BTN1 GPIO3 PRE") == []
    decoder.discard_partial()
    assert decoder.feed(b"SSED count=1\n") == []
    assert decoder.feed(b"BTN1 GPIO3 PRESSED count=2\n") == [1]
