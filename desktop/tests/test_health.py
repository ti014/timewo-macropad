"""Serial liveness tests use complete firmware replies, not just an open handle."""

from unittest.mock import Mock, patch

import pytest

from macropad.transport import Connection

STATUS = (
    b"ESP32-C3 macropad: 4-button test ready.\n"
    b"BTN1 GPIO3 PRESSED count=1\nBTN2 GPIO4 RELEASED count=0\n"
    b"BTN3 GPIO5 RELEASED count=0\nBTN4 GPIO6 RELEASED count=0\n"
)


def test_status_handshake_and_dead_handle() -> None:
    """A silently dead handle must time out even when reads raise no error."""
    handle = Mock(is_open=True, in_waiting=0)
    handle.write.return_value = 1
    connection = Connection()
    with patch("macropad.transport.serial.Serial", return_value=handle):
        connection.open("COM7")
    with patch("macropad.transport.monotonic", return_value=10):
        connection.request_status()
        assert not connection.confirmed
    handle.read.return_value = STATUS
    with patch("macropad.transport.monotonic", return_value=11):
        assert connection.poll() == []
        assert connection.confirmed
        connection.check_health()
    with patch("macropad.transport.monotonic", return_value=14):
        connection.check_health()
    assert handle.write.call_count == 2
    with patch("macropad.transport.monotonic", return_value=20), pytest.raises(OSError):
        connection.check_health()


def test_short_write_and_partial_reply_rejected() -> None:
    """Only a full four-button response confirms a live firmware session."""
    connection = Connection()
    handle = Mock(is_open=True, in_waiting=100)
    connection._serial = handle
    handle.write.return_value = 0
    with pytest.raises(OSError):
        connection.request_status()
    handle.write.return_value = 1
    connection.request_status()
    handle.read.return_value = STATUS.split(b"BTN4")[0]
    assert connection.poll() == []
    assert not connection.confirmed
