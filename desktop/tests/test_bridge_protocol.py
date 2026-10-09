"""Transport-neutral event identity and replay protection."""

import struct

import pytest

from macropad.bridge_protocol import ButtonPress, EventGate, decode_event, decode_state
from macropad.protocol import Decoder


def test_ble_event_and_state_are_bounded_and_versioned() -> None:
    event = decode_event(struct.pack("<BBII", 1, 2, 123, 7))
    assert event == 2
    assert (event.session, event.sequence) == (123, 7)
    assert decode_state(struct.pack("<BBII", 1, 0, 123, 7)) == (False, 123, 7)
    for packet in (b"", b"x" * 40, struct.pack("<BBII", 2, 2, 123, 7)):
        with pytest.raises(ValueError):
            decode_event(packet)
    with pytest.raises(ValueError):
        decode_event(struct.pack("<BBII", 1, 5, 123, 7))


def test_usb_and_ble_duplicate_cannot_execute_twice() -> None:
    gate = EventGate()
    event = ButtonPress(2, 123, 7)
    assert gate.accept(event)
    assert not gate.accept(decode_event(struct.pack("<BBII", 1, 2, 123, 7)))
    assert not gate.accept(ButtonPress(1, 123, 6))
    assert gate.accept(ButtonPress(2, 123, 8))


def test_gate_handles_reboot_and_sequence_wrap() -> None:
    gate = EventGate()
    assert gate.accept(ButtonPress(1, 123, 0xFFFFFFFF))
    assert gate.accept(ButtonPress(1, 123, 0))
    assert gate.accept(ButtonPress(1, 456, 1))
    assert not gate.accept(ButtonPress(1, 123, 1))


def test_usb_v2_emits_only_identified_events_not_legacy_echo() -> None:
    decoder = Decoder()
    assert decoder.feed(b"BRIDGE 1 123 0\n") == []
    assert decoder.feed(b"BTN2 GPIO4 PRESSED count=1\n") == []
    event = decoder.feed(b"EVT 123 7 2\n")[0]
    assert (event, event.session, event.sequence) == (2, 123, 7)
    assert decoder.feed(b"EVT 999 8 2\n") == []


def test_usb_reports_validated_bluetooth_address() -> None:
    decoder = Decoder()
    decoder.feed(b"BLE_ADDR 64:e8:33:8b:56:b2\n")
    assert decoder.ble_address == "64:E8:33:8B:56:B2"
    decoder.feed(b"BLE_ADDR invalid\n")
    assert decoder.ble_address == "64:E8:33:8B:56:B2"


def test_usb_distinguishes_radio_off_from_disconnected() -> None:
    decoder = Decoder()
    decoder.feed(b"BLE ON DISCONNECTED\n")
    assert decoder.ble_enabled is True
    decoder.feed(b"BLE OFF\n")
    assert decoder.ble_enabled is False
