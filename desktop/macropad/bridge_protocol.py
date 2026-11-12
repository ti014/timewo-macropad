"""Versioned BLE/USB events; no macro contents travel in button notifications."""

from collections import deque
from struct import Struct
from typing import Self

SERVICE_UUID = "a9141000-6ed1-4b32-9b4c-cb94de001001"
EVENT_UUID = "a9141001-6ed1-4b32-9b4c-cb94de001001"
COMMAND_UUID = "a9141002-6ed1-4b32-9b4c-cb94de001001"
STATE_UUID = "a9141003-6ed1-4b32-9b4c-cb94de001001"
PACKET = Struct("<BBII")
# Matches firmware kMaxButtons; serial lines carry the number as one digit.
MAX_BUTTONS = 9


class ButtonPress(int):
    """Button index with boot-session and monotonically increasing event ID."""

    def __new__(
        cls, button: int, session: int, sequence: int, *,
        pressed: bool = True, stateful: bool = True,
    ) -> Self:
        if button not in range(1, MAX_BUTTONS + 1) or not 0 <= session <= 0xFFFFFFFF:
            raise ValueError("Invalid button event")
        if not 0 <= sequence <= 0xFFFFFFFF:
            raise ValueError("Invalid event sequence")
        event = super().__new__(cls, button)
        event.session = session
        event.sequence = sequence
        event.pressed = pressed
        event.stateful = stateful
        return event


def decode_event(data: bytes) -> ButtonPress:
    """Decode a complete ten-byte notification, rejecting unknown versions."""
    if len(data) != PACKET.size:
        raise ValueError("Invalid BLE event size")
    version, button, session, sequence = PACKET.unpack(data)
    if version not in (1, 2):
        raise ValueError("Unsupported BLE protocol")
    return ButtonPress(button, session, sequence, pressed=version == 1)


def decode_state(data: bytes) -> tuple[bool, int, int]:
    """Return standalone mode, boot session and latest event watermark."""
    if len(data) != PACKET.size:
        raise ValueError("Invalid BLE state size")
    version, mode, session, sequence = PACKET.unpack(data)
    if version not in (1, 2) or mode not in (0, 1):
        raise ValueError("Unsupported BLE state")
    return bool(mode), session, sequence


class EventGate:
    """Reject cross-transport duplicates, reordered events and retired boots."""

    def __init__(self) -> None:
        self.session: int | None = None
        self.sequence: int | None = None
        self._retired: deque[int] = deque(maxlen=16)

    def accept(self, event: ButtonPress) -> bool:
        """Consume one fresh ID, including events ignored while paused."""
        if event.session in self._retired:
            return False
        if event.session != self.session:
            if self.session is not None:
                self._retired.append(self.session)
            self.session, self.sequence = event.session, None
        if self.sequence is not None:
            delta = (event.sequence - self.sequence) & 0xFFFFFFFF
            if not 0 < delta < 0x80000000:
                return False
        self.sequence = event.sequence
        return True
