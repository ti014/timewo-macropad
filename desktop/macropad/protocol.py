"""Bounded, incremental decoder for the already-flashed four-button firmware."""

import re

from .bridge_protocol import ButtonPress

LINE = re.compile(r"BTN([1-4]) GPIO([0-9]+) (PRESSED|RELEASED) count=([0-9]{1,10})")
PINS = {1: 3, 2: 4, 3: 5, 4: 6}


class Decoder:
    """Filter status snapshots and repeated press counts, preserving split lines."""

    def __init__(self) -> None:
        """Create an empty serial session."""
        self._buffer = bytearray()
        self._discard = False
        self._snapshot: set[int] = set()
        self._last: dict[int, int] = {}
        self.status_count = 0
        self.bridge_session: int | None = None
        self.ble_address: str | None = None
        self.ble_enabled: bool | None = None
        self.standalone = False

    def feed(self, data: bytes) -> list[int]:
        """Return only new physical button presses.

        Args:
            data: Arbitrarily chunked serial bytes.

        Returns:
            Button numbers in arrival order, excluding startup/status snapshots.
        """
        events = []
        for byte in data:
            if byte == 10:
                if not self._discard:
                    button = self._line(self._buffer.decode("ascii", errors="replace").strip())
                    if button is not None:
                        events.append(button)
                self._buffer.clear()
                self._discard = False
            elif not self._discard:
                self._buffer.append(byte)
                if len(self._buffer) > 512:
                    self._buffer.clear()
                    self._discard = True
        return events

    def _line(self, line: str) -> int | None:
        """Distinguish events from firmware's four-line status report."""
        fields = line.split()
        if fields[:2] == ["BLE", "OFF"]:
            self.ble_enabled = False
            return None
        if fields[:2] == ["BLE", "ON"]:
            self.ble_enabled = True
            return None
        if len(fields) == 2 and fields[0] == "BLE_ADDR":
            if re.fullmatch(r"(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}", fields[1]):
                self.ble_address = fields[1].upper()
            return None
        if len(fields) == 4 and fields[:2] == ["BRIDGE", "1"]:
            try:
                session, mode = int(fields[2]), int(fields[3])
            except ValueError:
                return None
            if 0 <= session <= 0xFFFFFFFF and mode in (0, 1):
                self.bridge_session, self.standalone = session, bool(mode)
            return None
        if len(fields) == 4 and fields[0] == "EVT":
            try:
                event = ButtonPress(int(fields[3]), int(fields[1]), int(fields[2]))
            except ValueError:
                return None
            return event if event.session == self.bridge_session else None
        if line == "ESP32-C3 macropad: 4-button test ready.":
            self._snapshot = set(PINS)
            self._last.clear()
            return None
        match = LINE.fullmatch(line)
        if match is None:
            return None
        button, pin, state, count = match.groups()
        button, pin, count = int(button), int(pin), int(count)
        if PINS[button] != pin or count > 0xFFFFFFFF:
            return None
        if button in self._snapshot:
            self._snapshot.remove(button)
            self._last[button] = count
            if not self._snapshot:
                self.status_count += 1
            return None
        previous = self._last.get(button)
        self._last[button] = count
        if self.bridge_session is None and state == "PRESSED" and previous != count:
            return button
        return None

    def discard_partial(self) -> None:
        """Drop a pre-arming partial packet so it cannot become a later event."""
        if self._buffer:
            self._buffer.clear()
            self._discard = True
