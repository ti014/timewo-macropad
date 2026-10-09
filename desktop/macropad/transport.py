"""Nonblocking USB serial session; never selects Bluetooth ports automatically."""

from time import monotonic

import serial
from serial.tools import list_ports

from .protocol import Decoder

UsbIdentity = tuple[int, int, str]
# Firmware drops the lease after 3 s; renew well inside that window.
LEASE_INTERVAL = 1.0


class Connection:
    """Own one serial handle and decoder, without background keyboard hooks."""

    def __init__(self) -> None:
        """Start disconnected."""
        self._serial: serial.Serial | None = None
        self._decoder = Decoder()
        self._pending_since: float | None = None
        self._last_status = 0.0
        self._next_lease = 0.0

    @property
    def connected(self) -> bool:
        """Return whether the serial handle is open."""
        return self._serial is not None and self._serial.is_open

    def open(self, port: str) -> None:
        """Connect without holding reset/boot control lines high.

        Args:
            port: Explicit serial port selected in the UI.

        Raises:
            serial.SerialException: If the port is absent or occupied by Monitor.
        """
        self.close()
        connection = serial.Serial(port=None, baudrate=115200, timeout=0, write_timeout=0.2)
        connection.dtr = False
        connection.rts = False
        connection.port = port
        try:
            connection.open()
            connection.reset_input_buffer()
            # Assert DTR for the firmware's Serial-connected check, not RTS/reset.
            connection.dtr = True
        except (OSError, serial.SerialException):
            connection.close()
            raise
        self._serial = connection
        self._decoder = Decoder()
        self._pending_since = None
        self._last_status = 0.0
        self._next_lease = 0.0

    @property
    def confirmed(self) -> bool:
        """Return whether this session received a complete firmware status reply."""
        return self._decoder.status_count > 0

    @property
    def bridge_session(self) -> int | None:
        """Boot ID shared with BLE, or None for legacy firmware."""
        return self._decoder.bridge_session

    @property
    def ble_enabled(self) -> bool | None:
        """Last radio state, distinct from an ordinary BLE disconnection."""
        return self._decoder.ble_enabled

    @property
    def ble_address(self) -> str | None:
        """Bluetooth address reported by the selected USB board."""
        return self._decoder.ble_address

    @property
    def standalone(self) -> bool:
        """Last device mode confirmed by a firmware status snapshot."""
        return self._decoder.standalone

    def request_status(self) -> None:
        """Ask the existing firmware for a harmless four-button status snapshot.

        Raises:
            serial.SerialException: If no handle exists or the request fails.
        """
        if self._serial is None or self._serial.write(b"?") != 1:
            raise serial.SerialException("Không gửi được yêu cầu kiểm tra board.")
        self._pending_since = monotonic()

    def send_command(self, command: str) -> None:
        """Send one newline-terminated firmware command over USB Serial."""
        if self._serial is None or not self.connected:
            raise serial.SerialException("Board chưa kết nối.")
        payload = command.encode("ascii")
        if not payload.endswith(b"\n"):
            payload += b"\n"
        if self._serial.write(payload) != len(payload):
            raise serial.SerialException("Không gửi đủ lệnh tới board.")

    def check_health(self) -> None:
        """Detect a stale COM handle even when Windows reports it as open.

        Raises:
            serial.SerialException: If a status request has no answer for five seconds.
        """
        now = monotonic()
        if self._pending_since is not None:
            if now - self._pending_since > 5:
                raise serial.SerialException("Board không trả lời kiểm tra USB trong 5 giây.")
        elif now - self._last_status >= 2:
            self.request_status()

    def _decode(self, data: bytes) -> list[int]:
        """Track complete status replies separately from actionable key presses."""
        previous = self._decoder.status_count
        events = self._decoder.feed(data)
        if self._decoder.status_count != previous:
            self._last_status = monotonic()
            self._pending_since = None
        return events

    def poll(self) -> list[int]:
        """Read bounded available data without waiting.

        Returns:
            New physical press events.

        Raises:
            serial.SerialException: If the board is unplugged or reading fails.
        """
        if self._serial is None:
            return []
        events = self._decode(self._serial.read(min(self._serial.in_waiting, 4096)))
        self._renew_lease()
        return events

    def _renew_lease(self) -> None:
        """Tell bridge firmware the app executes presses, so it must not type them too."""
        now = monotonic()
        if self._decoder.bridge_session is None or now < self._next_lease:
            return
        self._next_lease = now + LEASE_INTERVAL
        self.send_command("APP")

    def discard_pending(self) -> None:
        """Consume queued events before arming so old presses cannot execute.

        Raises:
            serial.SerialException: If reading fails.
        """
        if self._serial is not None:
            pending = self._serial.in_waiting
            if pending > 65536:
                self._serial.reset_input_buffer()
                raise serial.SerialException("Dữ liệu tồn đọng quá lớn; hãy kết nối lại board.")
            self._decode(self._serial.read(pending))
            self._decoder.discard_partial()

    def close(self) -> None:
        """Release COM port for PlatformIO upload or Serial Monitor."""
        if self._serial is not None:
            connection = self._serial
            self._serial = None
            if self._decoder.bridge_session is not None:
                try:
                    # Hand the keys back now instead of after the lease times out.
                    connection.write(b"APP OFF\n")
                    connection.flush()
                except (OSError, serial.SerialException):
                    pass
            connection.close()


def available_ports() -> list[tuple[str, str, bool]]:
    """List devices with Espressif USB ports first.

    Returns:
        Tuples of port name, friendly description and Espressif USB detection.
    """
    ports = [(port.device, port.description, port.vid == 0x303A) for port in list_ports.comports()]
    return sorted(ports, key=lambda item: (not item[2], item[0]))


def identify_usb_device(port: str) -> UsbIdentity | None:
    """Remember the physical Espressif device, not its changeable COM number.

    Args:
        port: Explicitly selected serial port.

    Returns:
        VID, PID and USB serial number, or None if safe identification is unavailable.
    """
    for device in list_ports.comports():
        if (
            device.device == port
            and device.vid == 0x303A
            and device.pid is not None
            and device.serial_number
        ):
            return device.vid, device.pid, device.serial_number
    return None


def find_usb_port(identity: UsbIdentity) -> str | None:
    """Locate exactly one instance of the previously selected physical board.

    Args:
        identity: VID, PID and serial number captured during manual connection.

    Returns:
        Current COM port, or None for absent or ambiguous matches.
    """
    matches = [
        device.device
        for device in list_ports.comports()
        if (device.vid, device.pid, device.serial_number) == identity
    ]
    return matches[0] if len(matches) == 1 else None
