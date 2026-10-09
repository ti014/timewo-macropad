"""Background BLE GATT transport; Qt and macro execution stay on the UI thread."""

import asyncio
import logging
import sys
import threading
from queue import Empty, Full, Queue
from time import monotonic

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice
from bleak.exc import BleakError

from .bridge_protocol import (
    COMMAND_UUID,
    EVENT_UUID,
    SERVICE_UUID,
    STATE_UUID,
    ButtonPress,
    EventGate,
    decode_event,
    decode_state,
)

# Retry the remembered Windows address this many times before rescanning.
ADDRESS_ATTEMPTS = 2
CONNECT_TIMEOUT = 12
# Firmware drops the app lease after 3 s; renew well inside that window.
LEASE_INTERVAL = 1.0
PAIRING_ERRORS = ("pair", "authenticat", "encrypt")


class BleConnection:
    """Reconnect one selected board, with bounded queues and an arming barrier."""

    def __init__(self) -> None:
        self.connected = False
        self.address: str | None = None
        self.standalone = False
        self.session: int | None = None
        self._capture = False
        self._generation = 0
        self._gate = EventGate()
        self._messages: Queue[tuple[str, object]] = Queue(maxsize=256)
        self._commands: Queue[tuple[str, object]] = Queue(maxsize=32)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._task: asyncio.Task | None = None
        self._failures = 0
        self._unpair = False

    @property
    def running(self) -> bool:
        """Whether the worker is active (including reconnect attempts)."""
        return self._thread is not None and self._thread.is_alive()

    def start(self, address: str | None = None) -> None:
        """Start only on explicit connect or a previously remembered selection."""
        if self.running:
            return
        self.poll()  # Do not replay lifecycle messages from an earlier worker.
        self._clear_commands()
        self._generation += 1
        self._capture = False
        self.address = address
        self._failures = 0
        self._unpair = False
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="macropad-ble", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Cancel discovery/connection without blocking the Qt event loop."""
        self._stop.set()
        self._capture = False
        self._generation += 1
        self.connected = False
        self._clear_commands()
        if self._loop is not None and self._task is not None:
            try:
                self._loop.call_soon_threadsafe(self._task.cancel)
            except RuntimeError:
                pass  # The worker already closed its event loop.

    def _clear_commands(self) -> None:
        """Drop commands that belong to a closed connection."""
        while True:
            try:
                self._commands.get_nowait()
            except Empty:
                return

    def poll(self) -> list[tuple[str, object]]:
        """Drain bounded notifications; never touch widgets from the worker."""
        messages = []
        for _ in range(256):
            try:
                messages.append(self._messages.get_nowait())
            except Empty:
                break
        return messages

    def set_capture(self, enabled: bool) -> None:
        """Close capture immediately; only a fresh board snapshot may reopen it."""
        self._generation += 1
        self._capture = False
        if enabled and self.connected:
            self._enqueue("barrier", self._generation)

    def send_commands(self, commands: list[str]) -> None:
        """Submit validated ASCII protocol lines, never arbitrary OS commands."""
        if not self.connected:
            raise OSError("Bluetooth chưa kết nối.")
        for command in commands:
            if not command.isascii() or "\n" in command or "\r" in command or len(command) > 1100:
                raise ValueError("Lệnh Bluetooth không hợp lệ.")
        self._enqueue("commands", tuple(commands))

    def _enqueue(self, kind: str, payload: object) -> None:
        try:
            self._commands.put_nowait((kind, payload))
        except Full as exc:
            self._capture = False
            raise OSError("Bluetooth đang bận; hãy thử lại.") from exc

    def _emit(self, kind: str, payload: object) -> None:
        try:
            self._messages.put_nowait((kind, payload))
        except Full:
            # Never replay an unbounded backlog or keep executing after overload.
            self._capture = False
            self.connected = False
            self._generation += 1
            self._stop.set()
            self.poll()
            self._messages.put_nowait(("error", "Bluetooth quá tải; đã bỏ sự kiện cũ và ngắt kết nối."))
            self._messages.put_nowait(("disconnected", None))

    def _set_state(self, data: bytes) -> None:
        standalone, session, sequence = decode_state(data)
        if standalone != self.standalone:
            self.set_capture(False)
        self.standalone, self.session = standalone, session
        self._gate.accept(ButtonPress(1, self.session, sequence))

    def _notify(self, _sender: object, data: bytearray) -> None:
        try:
            event = decode_event(data)
        except ValueError:
            return
        if event.session != self.session or self.standalone or not self._gate.accept(event):
            return
        self._emit("press", (event, self._capture, self._generation))

    def _run(self) -> None:
        try:
            asyncio.run(self._main())
        except asyncio.CancelledError:
            pass
        finally:
            self.connected = False
            self._capture = False
            self._emit("disconnected", None)
            self._loop = None
            self._task = None

    async def _find(self) -> BLEDevice:
        if self.address and sys.platform == "win32":
            if self._failures < ADDRESS_ATTEMPTS:
                # Windows can reopen a remembered device even while HID owns the link
                # and the board is no longer advertising. Bleak 3 uses its address.
                return BLEDevice(self.address, "timewo-macropad", None)
            # The remembered address keeps failing: look for an advertising board,
            # but keep the address when none is (HID may still hold the link).
            devices = await self._scan(timeout=3)
            if len(devices) == 1:
                return devices[0]
            return BLEDevice(self.address, "timewo-macropad", None)
        if self.address:
            device = await BleakScanner.find_device_by_address(self.address, timeout=5)
            if device is None:
                raise OSError("Chưa tìm thấy board đã ghi nhớ.")
            return device
        devices = await self._scan()
        if len(devices) != 1:
            raise OSError(
                "Chưa thấy board có firmware BLE bridge."
                if not devices else "Có nhiều board; chỉ bật board bạn muốn ghép."
            )
        return devices[0]

    @staticmethod
    async def _scan(timeout: float = 5, settle: float = 0.5) -> list[BLEDevice]:
        """Return bridge boards soon after the first is seen, not after the full timeout."""
        found: dict[str, BLEDevice] = {}
        first = asyncio.Event()

        def seen(device: BLEDevice, advertisement) -> None:
            # The bridge UUID lives in the scan response; bleak merges it here.
            if SERVICE_UUID in (uuid.lower() for uuid in advertisement.service_uuids):
                found[device.address] = device
                first.set()

        async with BleakScanner(seen):
            try:
                await asyncio.wait_for(first.wait(), timeout)
            except TimeoutError:
                return []
            await asyncio.sleep(settle)  # Long enough to notice a second board.
        return list(found.values())

    async def _main(self) -> None:
        self._loop = asyncio.get_running_loop()
        self._task = asyncio.current_task()
        previous_error = None
        while not self._stop.is_set():
            try:
                device = await self._find()
                if self._unpair:
                    # Windows keeps a key the board no longer has; pairing fresh is the only fix.
                    self._unpair = False
                    await BleakClient(device).unpair()
                async with BleakClient(device, pair=True, timeout=CONNECT_TIMEOUT) as client:
                    self._set_state(await asyncio.wait_for(client.read_gatt_char(STATE_UUID), 5))
                    await asyncio.wait_for(client.start_notify(EVENT_UUID, self._notify), 5)
                    self.address = device.address
                    self.connected = True
                    self._failures = 0
                    previous_error = None
                    self._emit("connected", (self.address, self.standalone, self.session))
                    await self._serve(client)
            except asyncio.CancelledError:
                raise
            except (BleakError, OSError, ValueError, RuntimeError) as exc:
                # BLE platform errors differ by OS; report and retry, never execute.
                self._failures += 1
                if sys.platform == "win32" and any(word in str(exc).lower() for word in PAIRING_ERRORS):
                    self._unpair = True
                message = str(exc) or (
                    "Hết thời gian chờ Bluetooth; đang thử lại. Kiểm tra radio trên board đã bật."
                    if isinstance(exc, TimeoutError) else type(exc).__name__
                )
                if message != previous_error:
                    logging.getLogger("macropad").warning("BLE: %s", message)
                    self._emit("error", message)
                    previous_error = message
            finally:
                self.connected = False
                self._capture = False
                self._generation += 1
                self._clear_commands()
                self._emit("disconnected", None)
            await asyncio.sleep(1)

    async def _serve(self, client: BleakClient) -> None:
        next_health = monotonic() + 2
        next_lease = 0.0
        while client.is_connected and not self._stop.is_set():
            if monotonic() >= next_lease:
                # Keep the board from typing presses this app is about to execute.
                await self._write(client, "APP")
                next_lease = monotonic() + LEASE_INTERVAL
            try:
                kind, payload = self._commands.get_nowait()
            except Empty:
                kind, payload = "", None
            if kind == "barrier":
                self._set_state(await asyncio.wait_for(client.read_gatt_char(STATE_UUID), 5))
                if payload == self._generation and not self.standalone:
                    self._capture = True
            elif kind == "commands":
                for command in payload:
                    await self._write(client, command)
                await asyncio.sleep(0.05)
                self._set_state(await asyncio.wait_for(client.read_gatt_char(STATE_UUID), 5))
                self._emit("mode", self.standalone)
                self._emit("commands_sent", None)
            if monotonic() >= next_health:
                standalone, session, _sequence = decode_state(
                    await asyncio.wait_for(client.read_gatt_char(STATE_UUID), 5)
                )
                if session != self.session:
                    raise OSError("Board đã khởi động lại; đồng bộ lại phiên BLE.")
                if standalone != self.standalone:
                    self.standalone = standalone
                    self.set_capture(False)
                    self._emit("mode", standalone)
                next_health = monotonic() + 2
            await asyncio.sleep(0.01)

    @staticmethod
    async def _write(client: BleakClient, command: str) -> None:
        # Leading newline recovers a receiver that discarded a partial write.
        data = ("\n" + command + "\n").encode("ascii")
        for offset in range(0, len(data), 20):
            await asyncio.wait_for(
                client.write_gatt_char(COMMAND_UUID, data[offset:offset + 20], response=True), 5
            )
