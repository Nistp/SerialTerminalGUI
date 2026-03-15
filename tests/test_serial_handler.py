"""Tests for app/serial_handler.py — SerialHandler state, capture mode, and read loop."""
import queue
import threading
from unittest.mock import MagicMock

import pytest

from app.serial_handler import Direction, SerialHandler, TerminalMessage


# ---------------------------------------------------------------------------
# TerminalMessage
# ---------------------------------------------------------------------------

class TestTerminalMessage:
    def test_direction_values(self):
        assert Direction.TX.value == "TX"
        assert Direction.RX.value == "RX"
        assert Direction.INFO.value == "INFO"
        assert Direction.ERROR.value == "ERROR"

    def test_frozen_text_not_mutable(self):
        msg = TerminalMessage(Direction.RX, "hello")
        with pytest.raises((AttributeError, TypeError)):
            msg.text = "world"

    def test_frozen_direction_not_mutable(self):
        msg = TerminalMessage(Direction.TX, "hi")
        with pytest.raises((AttributeError, TypeError)):
            msg.direction = Direction.RX

    def test_has_auto_timestamp(self):
        msg = TerminalMessage(Direction.INFO, "test")
        assert msg.timestamp is not None

    def test_explicit_timestamp_preserved(self):
        import datetime
        ts = datetime.datetime(2024, 1, 1, 12, 0, 0)
        msg = TerminalMessage(Direction.TX, "cmd", timestamp=ts)
        assert msg.timestamp == ts

    def test_equality_same_values(self):
        import datetime
        ts = datetime.datetime(2024, 6, 15, 10, 0, 0)
        a = TerminalMessage(Direction.RX, "data", timestamp=ts)
        b = TerminalMessage(Direction.RX, "data", timestamp=ts)
        assert a == b

    def test_inequality_different_text(self):
        import datetime
        ts = datetime.datetime(2024, 6, 15, 10, 0, 0)
        a = TerminalMessage(Direction.RX, "foo", timestamp=ts)
        b = TerminalMessage(Direction.RX, "bar", timestamp=ts)
        assert a != b


# ---------------------------------------------------------------------------
# SerialHandler — initial state
# ---------------------------------------------------------------------------

class TestSerialHandlerInitialState:
    def test_not_connected_initially(self):
        h = SerialHandler()
        assert not h.is_connected

    def test_rx_queue_is_queue_instance(self):
        h = SerialHandler()
        assert isinstance(h.rx_queue, queue.Queue)

    def test_rx_queue_is_empty_initially(self):
        h = SerialHandler()
        assert h.rx_queue.empty()

    def test_capture_queue_is_none_initially(self):
        h = SerialHandler()
        assert h.get_capture_queue() is None

    def test_is_not_running_initially(self):
        h = SerialHandler()
        assert h._thread is None


# ---------------------------------------------------------------------------
# Capture mode
# ---------------------------------------------------------------------------

class TestCaptureMode:
    def test_start_capture_creates_queue(self):
        h = SerialHandler()
        h.start_capture()
        assert isinstance(h.get_capture_queue(), queue.Queue)

    def test_stop_capture_removes_queue(self):
        h = SerialHandler()
        h.start_capture()
        h.stop_capture()
        assert h.get_capture_queue() is None

    def test_start_capture_creates_fresh_queue_each_call(self):
        h = SerialHandler()
        h.start_capture()
        q1 = h.get_capture_queue()
        h.stop_capture()
        h.start_capture()
        q2 = h.get_capture_queue()
        assert q1 is not q2

    def test_capture_queue_independent_of_rx_queue(self):
        h = SerialHandler()
        h.start_capture()
        assert h.get_capture_queue() is not h.rx_queue


# ---------------------------------------------------------------------------
# send() when not connected
# ---------------------------------------------------------------------------

class TestSendNotConnected:
    def test_send_raises_serial_exception_when_not_connected(self):
        import serial
        h = SerialHandler()
        with pytest.raises(serial.SerialException):
            h.send("AT", b"\r\n")

    def test_send_raises_when_serial_is_none(self):
        import serial
        h = SerialHandler()
        h._serial = None
        with pytest.raises(serial.SerialException):
            h.send("test", b"\n")


# ---------------------------------------------------------------------------
# disconnect() safety
# ---------------------------------------------------------------------------

class TestDisconnect:
    def test_disconnect_when_never_connected_is_safe(self):
        h = SerialHandler()
        h.disconnect()  # must not raise

    def test_disconnect_clears_capture_queue(self):
        h = SerialHandler()
        h.start_capture()
        # Inject a fake connected state so disconnect runs its cleanup path
        h._serial = MagicMock()
        h._serial.is_open = False
        h._thread = MagicMock()
        h._thread.join = MagicMock()
        h.disconnect()
        assert h.get_capture_queue() is None

    def test_disconnect_sets_serial_to_none(self):
        h = SerialHandler()
        mock_serial = MagicMock()
        mock_serial.is_open = True
        h._serial = mock_serial
        h._thread = MagicMock()
        h._thread.join = MagicMock()
        h.disconnect()
        assert h._serial is None
        assert not h.is_connected

    def test_disconnect_can_be_called_twice_safely(self):
        h = SerialHandler()
        h.disconnect()
        h.disconnect()  # second call must not raise


# ---------------------------------------------------------------------------
# Read loop — tested via a mock serial object
# ---------------------------------------------------------------------------

def _run_read_loop(handler: SerialHandler, chunks: list, stop_after_chunks: bool = True):
    """Drive _read_loop with pre-defined byte chunks from a mock serial port."""
    call_count = 0

    def fake_read(n):
        nonlocal call_count
        if call_count < len(chunks):
            data = chunks[call_count]
            call_count += 1
            return data
        handler._stop_event.set()
        return b""

    mock_serial = MagicMock()
    mock_serial.in_waiting = 1
    mock_serial.read.side_effect = fake_read
    handler._serial = mock_serial
    handler._stop_event.clear()

    t = threading.Thread(target=handler._read_loop, daemon=True)
    t.start()
    t.join(timeout=3.0)

    messages = []
    while not handler.rx_queue.empty():
        messages.append(handler.rx_queue.get_nowait())
    return messages


class TestReadLoop:
    def test_single_line_appears_in_rx_queue(self):
        h = SerialHandler()
        msgs = _run_read_loop(h, [b"hello\n"])
        assert any(m.text == "hello" for m in msgs)

    def test_cr_stripped_from_line(self):
        h = SerialHandler()
        msgs = _run_read_loop(h, [b"hello\r\n"])
        assert any(m.text == "hello" for m in msgs)

    def test_multiple_lines_in_one_chunk(self):
        h = SerialHandler()
        msgs = _run_read_loop(h, [b"line1\r\nline2\r\n"])
        texts = [m.text for m in msgs]
        assert "line1" in texts
        assert "line2" in texts

    def test_lines_split_across_chunks(self):
        h = SerialHandler()
        msgs = _run_read_loop(h, [b"hel", b"lo\n"])
        assert any(m.text == "hello" for m in msgs)

    def test_messages_have_rx_direction(self):
        h = SerialHandler()
        msgs = _run_read_loop(h, [b"data\n"])
        rx_msgs = [m for m in msgs if m.direction == Direction.RX]
        assert len(rx_msgs) >= 1

    def test_messages_also_go_to_capture_queue(self):
        h = SerialHandler()
        h.start_capture()
        cq = h.get_capture_queue()
        _run_read_loop(h, [b"response\n"])

        cap_texts = []
        while not cq.empty():
            cap_texts.append(cq.get_nowait().text)
        assert "response" in cap_texts

    def test_capture_queue_receives_same_messages_as_rx_queue(self):
        h = SerialHandler()
        h.start_capture()
        cq = h.get_capture_queue()
        msgs = _run_read_loop(h, [b"msg1\r\nmsg2\r\n"])

        rx_texts = {m.text for m in msgs}
        cap_texts = set()
        while not cq.empty():
            cap_texts.add(cq.get_nowait().text)

        assert rx_texts == cap_texts

    def test_no_capture_queue_does_not_crash(self):
        h = SerialHandler()
        # capture queue is None by default — loop must handle that silently
        msgs = _run_read_loop(h, [b"ok\n"])
        assert any(m.text == "ok" for m in msgs)

    def test_serial_exception_puts_error_message(self):
        import serial as pyserial
        h = SerialHandler()

        mock_serial = MagicMock()
        mock_serial.in_waiting = 1
        mock_serial.read.side_effect = pyserial.SerialException("port closed")
        h._serial = mock_serial
        h._stop_event.clear()

        t = threading.Thread(target=h._read_loop, daemon=True)
        t.start()
        t.join(timeout=3.0)

        msgs = []
        while not h.rx_queue.empty():
            msgs.append(h.rx_queue.get_nowait())
        assert any(m.direction == Direction.ERROR for m in msgs)

    def test_serial_exception_sets_stop_event(self):
        import serial as pyserial
        h = SerialHandler()

        mock_serial = MagicMock()
        mock_serial.in_waiting = 1
        mock_serial.read.side_effect = pyserial.SerialException("gone")
        h._serial = mock_serial
        h._stop_event.clear()

        t = threading.Thread(target=h._read_loop, daemon=True)
        t.start()
        t.join(timeout=3.0)

        assert h._stop_event.is_set()

    def test_generic_exception_puts_error_message(self):
        h = SerialHandler()

        mock_serial = MagicMock()
        mock_serial.in_waiting = 1
        mock_serial.read.side_effect = RuntimeError("unexpected")
        h._serial = mock_serial
        h._stop_event.clear()

        t = threading.Thread(target=h._read_loop, daemon=True)
        t.start()
        t.join(timeout=3.0)

        msgs = []
        while not h.rx_queue.empty():
            msgs.append(h.rx_queue.get_nowait())
        assert any(m.direction == Direction.ERROR for m in msgs)

    def test_utf8_decoding_errors_replaced_not_raised(self):
        h = SerialHandler()
        # 0xFF is invalid UTF-8 — should produce a replacement character, not raise
        msgs = _run_read_loop(h, [b"\xff\xfe\n"])
        assert len(msgs) >= 1
        assert msgs[0].direction != Direction.ERROR
