import datetime
import queue
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Direction(Enum):
    TX = "TX"
    RX = "RX"
    INFO = "INFO"
    ERROR = "ERROR"


@dataclass(frozen=True)
class TerminalMessage:
    direction: Direction
    text: str
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.now)


def list_serial_ports() -> list:
    """Return list of (device, description) tuples for available serial ports."""
    try:
        from serial.tools.list_ports import comports
        return [(p.device, p.description or p.device) for p in sorted(comports())]
    except Exception:
        return []


class SerialHandler:
    def __init__(self) -> None:
        self._serial = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._rx_queue: queue.Queue = queue.Queue()
        self._capture_queue: Optional[queue.Queue] = None

    @property
    def rx_queue(self) -> queue.Queue:
        return self._rx_queue

    @property
    def is_connected(self) -> bool:
        return self._serial is not None and self._serial.is_open

    def connect(self, port: str, baud: int, parity: str,
                databits: int, stopbits: float) -> None:
        import serial
        self._serial = serial.Serial(
            port=port,
            baudrate=baud,
            bytesize=databits,
            parity=parity,
            stopbits=stopbits,
            timeout=0.1,
            rtscts=False,
            dsrdtr=False,
        )
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._read_loop,
            daemon=True,
            name="serial-reader",
        )
        self._thread.start()

    def disconnect(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
            self._serial = None
        self._capture_queue = None

    def send(self, text: str, line_ending: bytes) -> None:
        import serial
        if self._serial is None or not self._serial.is_open:
            raise serial.SerialException("Not connected")
        self._serial.write(text.encode("utf-8") + line_ending)

    def start_capture(self) -> None:
        self._capture_queue = queue.Queue()

    def stop_capture(self) -> None:
        self._capture_queue = None

    def get_capture_queue(self) -> Optional[queue.Queue]:
        return self._capture_queue

    def _read_loop(self) -> None:
        import serial
        buf = bytearray()
        while not self._stop_event.is_set():
            try:
                chunk = self._serial.read(self._serial.in_waiting or 1)
                if chunk:
                    buf.extend(chunk)
                    lines = buf.split(b"\n")
                    buf = lines.pop()
                    for raw_line in lines:
                        text = raw_line.rstrip(b"\r").decode("utf-8", errors="replace")
                        msg = TerminalMessage(Direction.RX, text)
                        self._rx_queue.put(msg)
                        cq = self._capture_queue
                        if cq is not None:
                            cq.put(msg)
            except serial.SerialException as exc:
                err = TerminalMessage(Direction.ERROR, f"Port error: {exc}")
                self._rx_queue.put(err)
                self._stop_event.set()
                break
            except Exception as exc:
                err = TerminalMessage(Direction.ERROR, f"Read error: {exc}")
                self._rx_queue.put(err)
                self._stop_event.set()
                break
