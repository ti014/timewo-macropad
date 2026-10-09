"""BLE notifications are validated and never execute host actions in the worker."""

from macropad.ble_transport import BleConnection
from macropad.bridge_protocol import PACKET


def test_stop_invalidates_events_and_command_backlog() -> None:
    connection = BleConnection()
    connection.connected = True
    connection.set_capture(True)
    connection.send_commands(["MODE HID"])
    generation = connection._generation
    connection.stop()
    assert connection._generation > generation
    assert connection._commands.empty()
    assert not connection.connected


def test_overload_reports_error_and_discards_actionable_backlog() -> None:
    connection = BleConnection()
    connection.connected = True
    for _ in range(257):
        connection._emit("press", None)
    messages = connection.poll()
    assert not any(kind == "press" for kind, _ in messages)
    assert any(kind == "error" for kind, _ in messages)
    assert not connection.connected


def test_async_connection_retries_then_serves_and_closes(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    import macropad.ble_transport as transport

    connection = BleConnection()
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.read_gatt_char.return_value = PACKET.pack(1, 0, 123, 0)
    device = transport.BLEDevice("64:E8:33:8B:56:B2", "test-board", None)
    monkeypatch.setattr(connection, "_find", AsyncMock(side_effect=[OSError("temporary"), device]))
    monkeypatch.setattr(transport, "BleakClient", lambda *args, **kwargs: client)
    monkeypatch.setattr(transport.asyncio, "sleep", AsyncMock())

    async def serve(_client):
        assert connection.connected
        connection._stop.set()

    monkeypatch.setattr(connection, "_serve", serve)
    asyncio.run(connection._main())
    kinds = [kind for kind, _ in connection.poll()]
    assert kinds == ["error", "disconnected", "connected", "disconnected"]
    client.start_notify.assert_awaited_once()
    client.__aexit__.assert_awaited_once()
    assert not connection.connected


def test_windows_pairing_failure_unpairs_before_next_attempt(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from bleak.exc import BleakError

    import macropad.ble_transport as transport

    connection = BleConnection()
    stale = AsyncMock()
    stale.__aenter__.side_effect = BleakError("Could not pair with device: FAILED")
    fresh = AsyncMock()
    fresh.__aenter__.return_value = fresh
    fresh.read_gatt_char.return_value = PACKET.pack(1, 0, 123, 0)
    unpairer = AsyncMock()
    clients = iter([stale, unpairer, fresh])
    device = transport.BLEDevice("64:E8:33:8B:56:B2", "test-board", None)
    monkeypatch.setattr(transport.sys, "platform", "win32")
    monkeypatch.setattr(connection, "_find", AsyncMock(return_value=device))
    monkeypatch.setattr(transport, "BleakClient", lambda *args, **kwargs: next(clients))
    monkeypatch.setattr(transport.asyncio, "sleep", AsyncMock())

    async def serve(_client):
        connection._stop.set()

    monkeypatch.setattr(connection, "_serve", serve)
    asyncio.run(connection._main())
    unpairer.unpair.assert_awaited_once()
    assert not connection._unpair and connection._failures == 0


def test_windows_rescans_after_remembered_address_keeps_failing(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    import macropad.ble_transport as transport

    connection = BleConnection()
    connection.address = "64:E8:33:8B:56:B2"
    moved = transport.BLEDevice("11:22:33:44:55:66", "test-board", None)
    scan = AsyncMock(side_effect=[[moved], []])
    monkeypatch.setattr(transport.sys, "platform", "win32")
    monkeypatch.setattr(connection, "_scan", scan)
    assert asyncio.run(connection._find()).address == connection.address
    scan.assert_not_awaited()
    connection._failures = transport.ADDRESS_ATTEMPTS
    assert asyncio.run(connection._find()).address == moved.address
    # HID may own the link so nothing advertises; keep trying the remembered address.
    assert asyncio.run(connection._find()).address == connection.address


def test_notification_requires_current_session_and_fresh_sequence() -> None:
    connection = BleConnection()
    connection._set_state(PACKET.pack(1, 0, 100, 9))
    connection._notify(None, bytearray(PACKET.pack(1, 2, 100, 9)))
    connection._notify(None, bytearray(PACKET.pack(1, 2, 999, 10)))
    connection._notify(None, bytearray(b"invalid"))
    connection._notify(None, bytearray(PACKET.pack(1, 2, 100, 10)))
    messages = connection.poll()
    presses = [payload for kind, payload in messages if kind == "press"]
    assert len(presses) == 1
    event, captured, _generation = presses[0]
    assert (event, event.sequence, captured) == (2, 10, False)


def test_capture_is_closed_until_async_barrier_and_after_disconnect() -> None:
    connection = BleConnection()
    connection._capture = True
    connection.set_capture(True)
    assert not connection._capture
    connection._capture = True
    connection.set_capture(False)
    assert not connection._capture


def test_commands_reject_embedded_newline_and_disconnected_session() -> None:
    import pytest

    connection = BleConnection()
    with pytest.raises(OSError):
        connection.send_commands(["MODE APP"])
    connection.connected = True
    with pytest.raises(ValueError):
        connection.send_commands(["MODE APP\nMODE HID"])


def test_standalone_never_delivers_app_actions() -> None:
    connection = BleConnection()
    connection._set_state(PACKET.pack(1, 1, 100, 0))
    connection._notify(None, bytearray(PACKET.pack(1, 2, 100, 1)))
    assert not any(kind == "press" for kind, _ in connection.poll())


def test_async_barrier_reopens_only_current_generation() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    connection = BleConnection()
    connection.connected = True
    connection.set_capture(True)
    client = AsyncMock()
    client.is_connected = True

    async def read(_uuid):
        client.is_connected = False
        return PACKET.pack(1, 0, 123, 9)

    client.read_gatt_char.side_effect = read
    asyncio.run(connection._serve(client))
    connection._notify(None, bytearray(PACKET.pack(1, 2, 123, 10)))
    event, captured, generation = connection.poll()[0][1]
    assert captured and generation == connection._generation
    assert event.sequence == 10

    connection.set_capture(True)
    connection.set_capture(False)
    client.is_connected = True
    asyncio.run(connection._serve(client))
    assert not connection._capture


def test_async_commands_are_chunked_and_mode_read_back() -> None:
    import asyncio
    from unittest.mock import AsyncMock

    from macropad.bridge_protocol import COMMAND_UUID

    connection = BleConnection()
    connection.connected = True
    command = "SYNC 1 1 " + "41" * 25
    connection.send_commands([command, "MODE HID"])
    client = AsyncMock()
    client.is_connected = True

    async def read(_uuid):
        client.is_connected = False
        return PACKET.pack(1, 1, 123, 0)

    client.read_gatt_char.side_effect = read
    asyncio.run(connection._serve(client))
    chunks = client.write_gatt_char.await_args_list
    assert all(call.args[0] == COMMAND_UUID and len(call.args[1]) <= 20 for call in chunks)
    assert all(call.kwargs == {"response": True} for call in chunks)
    # The lease goes first so the board never types a press the app executes.
    assert b"".join(call.args[1] for call in chunks) == f"\nAPP\n\n{command}\n\nMODE HID\n".encode()
    assert ("mode", True) in connection.poll()


def test_health_check_detects_reboot_and_rejects_stale_capture(monkeypatch) -> None:
    import asyncio
    from unittest.mock import AsyncMock

    import pytest

    import macropad.ble_transport as transport

    connection = BleConnection()
    connection._set_state(PACKET.pack(1, 0, 123, 0))
    clock = iter((0, 0, 0, 3))  # health deadline, lease check + renewal, health check
    monkeypatch.setattr(transport, "monotonic", lambda: next(clock))
    client = AsyncMock()
    client.is_connected = True
    client.read_gatt_char.return_value = PACKET.pack(1, 0, 456, 0)
    with pytest.raises(OSError, match="khởi động lại"):
        asyncio.run(connection._serve(client))


def test_state_change_invalidates_pending_presses() -> None:
    connection = BleConnection()
    connection._capture = True
    generation = connection._generation
    connection._set_state(PACKET.pack(1, 1, 123, 0))
    assert connection._generation > generation
    assert not connection._capture
