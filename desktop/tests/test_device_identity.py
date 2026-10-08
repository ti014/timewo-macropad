"""Verify board identity matching independently from changeable COM numbers."""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from macropad.transport import find_usb_port, identify_usb_device


def _device(
    port: str, serial: str | None, vid: int | None = 0x303A, pid: int | None = 0x1001
) -> SimpleNamespace:
    """Construct minimal device metadata without opening a serial handle."""
    return SimpleNamespace(device=port, serial_number=serial, vid=vid, pid=pid)


def test_identity_follows_same_board_to_different_port() -> None:
    """A USB serial number remains stable when Windows changes COM allocation."""
    with patch("macropad.transport.list_ports.comports", return_value=[_device("COM7", "BOARD-A")]):
        identity = identify_usb_device("COM7")
    assert identity == (0x303A, 0x1001, "BOARD-A")
    with patch(
        "macropad.transport.list_ports.comports",
        return_value=[_device("COM7", "BOARD-B"), _device("COM9", "BOARD-A")],
    ):
        assert find_usb_port(identity) == "COM9"


@pytest.mark.parametrize(
    "devices",
    [
        [],
        [_device("COM7", "BOARD-B")],
        [_device("COM7", "BOARD-A", vid=0x1234)],
        [_device("COM7", "BOARD-A", pid=0x2222)],
        [_device("COM7", "BOARD-A"), _device("COM8", "BOARD-A")],
    ],
)
def test_absent_wrong_or_ambiguous_device_is_rejected(devices: list) -> None:
    """Do not connect to a lookalike, reused port or duplicate identity."""
    with patch("macropad.transport.list_ports.comports", return_value=devices):
        assert find_usb_port((0x303A, 0x1001, "BOARD-A")) is None


@pytest.mark.parametrize(
    "device",
    [
        _device("COM3", "BOARD-A"),
        _device("COM7", None),
        _device("COM7", "BOARD-A", vid=None),
        _device("COM7", "BOARD-A", pid=None),
    ],
)
def test_unknown_device_is_not_remembered(device: SimpleNamespace) -> None:
    """Unavailable or non-Espressif identities disable automatic reconnect."""
    with patch("macropad.transport.list_ports.comports", return_value=[device]):
        assert identify_usb_device("COM7") is None
