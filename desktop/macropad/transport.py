"""Nonblocking USB serial session; never selects Bluetooth ports automatically."""

from time import monotonic, sleep

import serial
from serial.tools import list_ports

from .protocol import Decoder

UsbIdentity = tuple[int, int, str]
# Espressif native USB, plus the USB-UART bridges used on most ESP32 dev boards
# (Silicon Labs CP210x, WCH CH340/CH9102, FTDI).
ESPRESSIF_VID = 0x303A
BOARD_VIDS = {ESPRESSIF_VID, 0x10C4, 0x1A86, 0x0403}
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
        self._held: list[int] = []

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
            # Native USB firmware needs DTR for its Serial-connected check. On USB-UART
            # boards DTR drives IO0 through the auto-reset circuit, so leave it low there.
            connection.dtr = not _is_uart_bridge(port)
        except (OSError, serial.SerialException):
            connection.close()
            raise
        self._serial = connection
        self._decoder = Decoder()
        self._pending_since = None
        self._last_status = 0.0
        self._next_lease = 0.0
        self._held = []

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
    def pins(self) -> dict[int, int]:
        """Button number to GPIO, as reported by the board's last status snapshot."""
        return self._decoder.pins

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
        events, self._held = self._held, []
        events += self._decode(self._serial.read(min(self._serial.in_waiting, 4096)))
        self._renew_lease()
        return events

    def request(self, command: str, end: str, timeout: float = 2.0) -> list[str]:
        """Send a command and wait for its reply lines, keeping presses for the next poll.

        Args:
            command: Firmware command such as ``INFO``.
            end: Prefix of the reply line that completes the answer, e.g. ``INFO END``.
            timeout: Seconds to wait before giving up.

        Returns:
            Reply lines received after sending, up to and including the end line.

        Raises:
            serial.SerialException: On timeout or when the board is disconnected.
        """
        if self._serial is None:
            raise serial.SerialException("Board chưa kết nối.")
        self._held += self._decode(self._serial.read(self._serial.in_waiting))
        self._decoder.replies.clear()
        self.send_command(command)
        deadline = monotonic() + timeout
        while True:
            replies = self._decoder.replies
            for index, line in enumerate(replies):
                if line.startswith(end):
                    return replies[: index + 1]
            if monotonic() > deadline:
                raise serial.SerialException(f"Board không trả lời lệnh {command.split()[0]}.")
            sleep(0.01)
            self._held += self._decode(self._serial.read(self._serial.in_waiting))

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


def _is_uart_bridge(port: str) -> bool:
    """Whether ``port`` is a known USB-UART bridge rather than Espressif native USB."""
    return any(
        device.device == port and device.vid in BOARD_VIDS - {ESPRESSIF_VID}
        for device in list_ports.comports()
    )


def available_ports() -> list[tuple[str, str, bool]]:
    """List likely ESP32 boards first: Espressif USB, then common USB-UART bridges.

    Returns:
        Tuples of port name, friendly description and likely-board detection.
    """
    ports = [
        (port.device, port.description, port.vid in BOARD_VIDS) for port in list_ports.comports()
    ]
    return sorted(ports, key=lambda item: (not item[2], item[0]))


def identify_usb_device(port: str) -> UsbIdentity | None:
    """Remember the physical board, not its changeable COM number.

    Bridges without a USB serial number (most CH340) cannot be told apart, so they
    get no identity and reconnect manually.

    Args:
        port: Explicitly selected serial port.

    Returns:
        VID, PID and USB serial number, or None if safe identification is unavailable.
    """
    for device in list_ports.comports():
        if (
            device.device == port
            and device.vid in BOARD_VIDS
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
