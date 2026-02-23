import queue
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from app.serial_handler import Direction, SerialHandler, TerminalMessage

# Tokens that can appear literally in navigation command strings and will be
# expanded to the corresponding control characters before sending.
_ESCAPE_SEQUENCES: dict = {
    "<ESC>": "\x1b",
}


def _expand_escapes(cmd: str) -> str:
    for token, replacement in _ESCAPE_SEQUENCES.items():
        cmd = cmd.replace(token, replacement)
    return cmd


@dataclass
class TestCase:
    name: str
    command: str
    expected: str
    terminator: str = "OK"
    timeout_ms: int = 2000
    enabled: bool = True
    # Navigation commands executed silently before/after the test command.
    # They are NOT echoed to the terminal and NOT written to the session log.
    setup_commands: List[str] = field(default_factory=list)
    teardown_commands: List[str] = field(default_factory=list)
    # Timeout for each individual navigation command (setup/teardown step).
    nav_timeout_ms: int = 1000
    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "command": self.command,
            "expected": self.expected,
            "terminator": self.terminator,
            "timeout_ms": self.timeout_ms,
            "enabled": self.enabled,
            "setup_commands": self.setup_commands,
            "teardown_commands": self.teardown_commands,
            "nav_timeout_ms": self.nav_timeout_ms,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "TestCase":
        return cls(
            id=d.get("id", str(uuid.uuid4())),
            name=d.get("name", ""),
            command=d.get("command", ""),
            expected=d.get("expected", ""),
            terminator=d.get("terminator", "OK"),
            timeout_ms=int(d.get("timeout_ms", 2000)),
            enabled=bool(d.get("enabled", True)),
            setup_commands=d.get("setup_commands", []),
            teardown_commands=d.get("teardown_commands", []),
            nav_timeout_ms=int(d.get("nav_timeout_ms", 1000)),
        )


@dataclass
class TestResult:
    test: TestCase
    status: str          # "PASS" | "FAIL" | "TIMEOUT" | "ERROR"
    actual: str          # all lines received, joined with newlines
    duration_ms: float


class TestRunner:
    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def run(
        self,
        tests: List[TestCase],
        handler: SerialHandler,
        line_ending: bytes,
        on_result: Callable[[TestResult], None],
        on_done: Callable[[], None],
        delay_ms: int = 200,
    ) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(tests, handler, line_ending, on_result, on_done, delay_ms),
            daemon=True,
            name="test-runner",
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()

    def _run_loop(
        self,
        tests: List[TestCase],
        handler: SerialHandler,
        line_ending: bytes,
        on_result: Callable[[TestResult], None],
        on_done: Callable[[], None],
        delay_ms: int,
    ) -> None:
        for test in tests:
            if self._stop_event.is_set():
                break

            result = self._execute_test(test, handler, line_ending)
            on_result(result)

            if self._stop_event.is_set():
                break

            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        on_done()

    def _execute_silent(
        self,
        cmd: str,
        handler: SerialHandler,
        line_ending: bytes,
        terminator: str,
        timeout_ms: int,
    ) -> None:
        """Send a navigation command without touching rx_queue.

        Because nothing is put into rx_queue, the command and its response
        never reach the terminal display or the session log.
        """
        handler.start_capture()
        cq = handler.get_capture_queue()
        try:
            handler.send(_expand_escapes(cmd), line_ending)
        except Exception:
            handler.stop_capture()
            return

        timeout_s = timeout_ms / 1000.0
        t_start = time.monotonic()
        while True:
            elapsed = time.monotonic() - t_start
            if elapsed >= timeout_s:
                break
            try:
                msg = cq.get(timeout=min(timeout_s - elapsed, 0.05))
                if terminator and terminator in msg.text:
                    break
            except queue.Empty:
                pass

        handler.stop_capture()

    def _execute_test(
        self,
        test: TestCase,
        handler: SerialHandler,
        line_ending: bytes,
    ) -> TestResult:
        if not handler.is_connected:
            return TestResult(
                test=test,
                status="ERROR",
                actual="Not connected",
                duration_ms=0.0,
            )

        # --- Silent setup (menu navigation) ---
        for cmd in test.setup_commands:
            if cmd.strip():
                self._execute_silent(
                    cmd.strip(), handler, line_ending,
                    test.terminator, test.nav_timeout_ms,
                )

        # --- Visible test command ---
        handler.start_capture()
        cq = handler.get_capture_queue()
        collected_lines: List[str] = []
        t_start = time.monotonic()

        try:
            # Echo TX into main rx_queue so it appears in terminal
            handler.rx_queue.put(TerminalMessage(Direction.TX, test.command))
            handler.send(test.command, line_ending)
        except Exception as exc:
            handler.stop_capture()
            # Still run teardown before returning
            for cmd in test.teardown_commands:
                if cmd.strip():
                    self._execute_silent(
                        cmd.strip(), handler, line_ending,
                        test.terminator, test.nav_timeout_ms,
                    )
            return TestResult(
                test=test,
                status="ERROR",
                actual=f"Send failed: {exc}",
                duration_ms=0.0,
            )

        timeout_s = test.timeout_ms / 1000.0
        terminator_found = False

        while True:
            elapsed = time.monotonic() - t_start
            remaining = timeout_s - elapsed
            if remaining <= 0:
                break

            try:
                msg = cq.get(timeout=min(remaining, 0.05))
                collected_lines.append(msg.text)
                if test.terminator and test.terminator in msg.text:
                    terminator_found = True
                    break
            except queue.Empty:
                if time.monotonic() - t_start >= timeout_s:
                    break

        handler.stop_capture()
        duration_ms = (time.monotonic() - t_start) * 1000.0
        actual = "\n".join(collected_lines)

        if not terminator_found and test.terminator:
            status = "TIMEOUT"
        elif test.expected and test.expected not in actual:
            status = "FAIL"
        else:
            status = "PASS"

        # --- Silent teardown (return to parent menu) ---
        for cmd in test.teardown_commands:
            if cmd.strip():
                self._execute_silent(
                    cmd.strip(), handler, line_ending,
                    test.terminator, test.nav_timeout_ms,
                )

        return TestResult(test=test, status=status, actual=actual, duration_ms=duration_ms)
