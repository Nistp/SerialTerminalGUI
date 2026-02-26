import queue
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

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


# Matches lines of the form:  <optional prefix>  <op>  <threshold>
# Supported ops: >= <= > < == != in
_CHECK_RE = re.compile(r'^(.*?)\s*(>=|<=|!=|==|>|<|in)\s+(.+)$')
# Extracts the first integer or float (with optional sign and exponent)
_NUMBER_RE = re.compile(r'[-+]?\d+(?:\.\d+)?(?:[eE][-+]?\d+)?')


def _evaluate_numeric_checks(checks_str: str, actual: str) -> Tuple[bool, List[str]]:
    """Evaluate newline-separated numeric assertions against *actual*.

    Each non-empty line must follow one of these formats::

        <prefix> <op> <value>       # e.g.  +CSQ: >= 5
        <prefix> in <lo>..<hi>      # e.g.  TEMP: in 15.0..35.0

    *prefix* (may be empty) is searched literally in *actual*; the first
    number found after it is extracted and compared.  If prefix is empty the
    first number anywhere in the response is used.

    Returns ``(all_passed, failure_messages)``.
    """
    if not checks_str.strip():
        return True, []

    failures: List[str] = []
    for raw in checks_str.split("\n"):
        line = raw.strip()
        if not line:
            continue

        m = _CHECK_RE.match(line)
        if not m:
            failures.append(f"Bad syntax: {line!r}")
            continue

        prefix = m.group(1).strip()
        op     = m.group(2)
        rhs    = m.group(3).strip()

        # Locate search region
        search_in = actual
        if prefix:
            idx = actual.find(prefix)
            if idx == -1:
                failures.append(f"Prefix not found: {prefix!r}")
                continue
            search_in = actual[idx + len(prefix):]

        num_m = _NUMBER_RE.search(search_in)
        if not num_m:
            loc = f"after {prefix!r}" if prefix else "in response"
            failures.append(f"No number {loc}")
            continue

        value = float(num_m.group())

        if op == "in":
            parts = rhs.split("..")
            if len(parts) != 2:
                failures.append(f"Bad range (expected lo..hi): {rhs!r}")
                continue
            try:
                lo, hi = float(parts[0].strip()), float(parts[1].strip())
            except ValueError:
                failures.append(f"Non-numeric range bounds: {rhs!r}")
                continue
            if not (lo <= value <= hi):
                loc = f" (after {prefix!r})" if prefix else ""
                failures.append(f"{value} not in [{lo}..{hi}]{loc}")
        else:
            try:
                threshold = float(rhs)
            except ValueError:
                failures.append(f"Non-numeric threshold: {rhs!r}")
                continue
            result = {
                ">=": value >= threshold,
                "<=": value <= threshold,
                ">":  value > threshold,
                "<":  value < threshold,
                "==": value == threshold,
                "!=": value != threshold,
            }[op]
            if not result:
                loc = f" (after {prefix!r})" if prefix else ""
                failures.append(f"{value} {op} {threshold} failed{loc}")

    return len(failures) == 0, failures


@dataclass
class TestCase:
    name: str
    command: str
    expected: str
    terminator: str = "OK"
    timeout_ms: int = 2000
    enabled: bool = True
    # If True, the runner pauses and asks the user for the verdict instead of
    # evaluating the response automatically.
    manual: bool = False
    # Navigation commands executed silently before/after the test command.
    # They are NOT echoed to the terminal and NOT written to the session log.
    setup_commands: List[str] = field(default_factory=list)
    teardown_commands: List[str] = field(default_factory=list)
    # Timeout for each individual navigation command (setup/teardown step).
    nav_timeout_ms: int = 1000
    # Newline-separated numeric assertions: "<prefix> <op> <value>"
    numeric_checks: str = ""
    # Commands sent fire-and-forget to the secondary trigger port.
    trigger_commands: List[str] = field(default_factory=list)
    # When to fire: "before_setup" (default) or "after_setup"
    trigger_timing: str = "before_setup"
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
            "manual": self.manual,
            "setup_commands": self.setup_commands,
            "teardown_commands": self.teardown_commands,
            "nav_timeout_ms": self.nav_timeout_ms,
            "numeric_checks": self.numeric_checks,
            "trigger_commands": self.trigger_commands,
            "trigger_timing": self.trigger_timing,
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
            manual=bool(d.get("manual", False)),
            setup_commands=d.get("setup_commands", []),
            teardown_commands=d.get("teardown_commands", []),
            nav_timeout_ms=int(d.get("nav_timeout_ms", 1000)),
            numeric_checks=d.get("numeric_checks", ""),
            trigger_commands=d.get("trigger_commands", []),
            trigger_timing=d.get("trigger_timing", "before_setup"),
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
        # Used to synchronise the runner thread with the GUI during manual tests.
        self._manual_event = threading.Event()
        self._manual_result: Optional[Tuple[str, str]] = None

    def set_manual_result(self, status: str, actual: str) -> None:
        """Called from the GUI thread after the user submits their verdict."""
        self._manual_result = (status, actual)
        self._manual_event.set()

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
        trigger_handler: Optional[SerialHandler] = None,
        on_manual_input: Optional[Callable[["TestCase"], None]] = None,
    ) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            args=(tests, handler, line_ending, on_result, on_done, delay_ms,
                  trigger_handler, on_manual_input),
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
        trigger_handler: Optional[SerialHandler] = None,
        on_manual_input: Optional[Callable[["TestCase"], None]] = None,
    ) -> None:
        for test in tests:
            if self._stop_event.is_set():
                break

            result = self._execute_test(test, handler, line_ending, trigger_handler, on_manual_input)
            on_result(result)

            if self._stop_event.is_set():
                break

            if delay_ms > 0:
                time.sleep(delay_ms / 1000.0)

        on_done()

    def _execute_trigger(
        self,
        cmd: str,
        trigger_handler: SerialHandler,
        line_ending: bytes,
    ) -> None:
        """Fire-and-forget send to the secondary trigger port."""
        try:
            trigger_handler.send(_expand_escapes(cmd), line_ending)
        except Exception:
            pass

    def _run_trigger_commands(
        self,
        test: "TestCase",
        trigger_handler: Optional[SerialHandler],
        line_ending: bytes,
    ) -> None:
        if trigger_handler is not None and trigger_handler.is_connected:
            for cmd in test.trigger_commands:
                if cmd.strip():
                    self._execute_trigger(cmd.strip(), trigger_handler, line_ending)

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

    def _execute_manual(
        self,
        test: TestCase,
        handler: SerialHandler,
        line_ending: bytes,
        on_manual_input: Optional[Callable[["TestCase"], None]],
    ) -> TestResult:
        """Send the command (if any), then block until the user provides a verdict."""
        t_start = time.monotonic()

        if test.command.strip():
            try:
                handler.rx_queue.put(TerminalMessage(Direction.TX, test.command))
                handler.send(test.command, line_ending)
            except Exception as exc:
                for cmd in test.teardown_commands:
                    if cmd.strip():
                        self._execute_silent(cmd.strip(), handler, line_ending,
                                             test.terminator, test.nav_timeout_ms)
                return TestResult(test=test, status="ERROR",
                                  actual=f"Send failed: {exc}",
                                  duration_ms=(time.monotonic() - t_start) * 1000.0)

        # Signal the GUI to show the verdict dialog.
        self._manual_event.clear()
        self._manual_result = None
        if on_manual_input is not None:
            on_manual_input(test)

        # Block until the user submits, or the run is stopped.
        while not self._manual_event.is_set():
            if self._stop_event.is_set():
                for cmd in test.teardown_commands:
                    if cmd.strip():
                        self._execute_silent(cmd.strip(), handler, line_ending,
                                             test.terminator, test.nav_timeout_ms)
                return TestResult(test=test, status="ERROR",
                                  actual="Run stopped while waiting for manual verdict",
                                  duration_ms=(time.monotonic() - t_start) * 1000.0)
            time.sleep(0.05)

        duration_ms = (time.monotonic() - t_start) * 1000.0
        status, actual = self._manual_result or ("ERROR", "No result provided")

        for cmd in test.teardown_commands:
            if cmd.strip():
                self._execute_silent(cmd.strip(), handler, line_ending,
                                     test.terminator, test.nav_timeout_ms)

        return TestResult(test=test, status=status, actual=actual, duration_ms=duration_ms)

    def _execute_test(
        self,
        test: TestCase,
        handler: SerialHandler,
        line_ending: bytes,
        trigger_handler: Optional[SerialHandler] = None,
        on_manual_input: Optional[Callable[["TestCase"], None]] = None,
    ) -> TestResult:
        if not handler.is_connected:
            return TestResult(
                test=test,
                status="ERROR",
                actual="Not connected",
                duration_ms=0.0,
            )

        # --- Trigger commands (before setup, if configured) ---
        if test.trigger_timing == "before_setup":
            self._run_trigger_commands(test, trigger_handler, line_ending)

        # --- Silent setup (menu navigation) ---
        for cmd in test.setup_commands:
            if cmd.strip():
                self._execute_silent(
                    cmd.strip(), handler, line_ending,
                    test.terminator, test.nav_timeout_ms,
                )

        # --- Trigger commands (after setup, if configured) ---
        if test.trigger_timing == "after_setup":
            self._run_trigger_commands(test, trigger_handler, line_ending)

        # --- Manual test: pause and wait for user verdict ---
        if test.manual:
            return self._execute_manual(test, handler, line_ending, on_manual_input)

        # --- Visible test command (automated) ---
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
        else:
            # Substring pattern check
            if test.expected:
                patterns = [p.strip() for p in test.expected.split("\n") if p.strip()]
                sub_ok = all(p in actual for p in patterns)
            else:
                sub_ok = True

            # Numeric limit check
            if test.numeric_checks:
                num_ok, num_failures = _evaluate_numeric_checks(test.numeric_checks, actual)
                if not num_ok:
                    actual = actual + "\n[numeric checks]\n" + "\n".join(num_failures)
            else:
                num_ok = True

            status = "PASS" if (sub_ok and num_ok) else "FAIL"

        # --- Silent teardown (return to parent menu) ---
        for cmd in test.teardown_commands:
            if cmd.strip():
                self._execute_silent(
                    cmd.strip(), handler, line_ending,
                    test.terminator, test.nav_timeout_ms,
                )

        return TestResult(test=test, status=status, actual=actual, duration_ms=duration_ms)
