"""Tests for app/test_runner.py — numeric checks, TestCase serialization, TestRunner execution."""
import queue
import threading
import time
import uuid

import pytest

from app.serial_handler import Direction, SerialHandler, TerminalMessage
from app.test_runner import (
    TestCase,
    TestResult,
    TestRunner,
    _evaluate_numeric_checks,
    _expand_escapes,
)


# ---------------------------------------------------------------------------
# _expand_escapes
# ---------------------------------------------------------------------------

class TestExpandEscapes:
    def test_esc_token_replaced(self):
        assert _expand_escapes("<ESC>") == "\x1b"

    def test_esc_token_in_middle_of_string(self):
        result = _expand_escapes("menu<ESC>back")
        assert "\x1b" in result
        assert "<ESC>" not in result

    def test_multiple_esc_tokens(self):
        result = _expand_escapes("<ESC><ESC>")
        assert result == "\x1b\x1b"

    def test_no_tokens_unchanged(self):
        assert _expand_escapes("AT+CSQ") == "AT+CSQ"

    def test_empty_string_unchanged(self):
        assert _expand_escapes("") == ""


# ---------------------------------------------------------------------------
# _evaluate_numeric_checks
# ---------------------------------------------------------------------------

class TestEvaluateNumericChecks:
    # --- Empty / blank input ---

    def test_empty_string_passes(self):
        ok, failures = _evaluate_numeric_checks("", "anything")
        assert ok
        assert failures == []

    def test_blank_lines_only_passes(self):
        ok, failures = _evaluate_numeric_checks("   \n  \n", "anything")
        assert ok

    # --- Comparison operators: passing ---

    def test_gte_passes(self):
        ok, _ = _evaluate_numeric_checks(">= 5", "+CSQ: 10\r\nOK")
        assert ok

    def test_gte_equal_passes(self):
        ok, _ = _evaluate_numeric_checks(">= 10", "value 10 done")
        assert ok

    def test_lte_passes(self):
        ok, _ = _evaluate_numeric_checks("<= 100", "temp 50 C")
        assert ok

    def test_lt_passes(self):
        ok, _ = _evaluate_numeric_checks("< 100", "temp 50")
        assert ok

    def test_gt_passes(self):
        ok, _ = _evaluate_numeric_checks("> 0", "signal 5")
        assert ok

    def test_eq_passes(self):
        ok, _ = _evaluate_numeric_checks("== 42", "answer 42")
        assert ok

    def test_neq_passes(self):
        ok, _ = _evaluate_numeric_checks("!= 0", "count 1")
        assert ok

    # --- Comparison operators: failing ---

    def test_gte_fails(self):
        ok, failures = _evaluate_numeric_checks(">= 20", "value 10")
        assert not ok
        assert len(failures) == 1

    def test_lte_fails(self):
        ok, failures = _evaluate_numeric_checks("<= 5", "value 10")
        assert not ok

    def test_lt_fails_on_equal(self):
        ok, _ = _evaluate_numeric_checks("< 10", "value 10")
        assert not ok

    def test_gt_fails_on_equal(self):
        ok, _ = _evaluate_numeric_checks("> 10", "value 10")
        assert not ok

    def test_eq_fails(self):
        ok, _ = _evaluate_numeric_checks("== 5", "value 10")
        assert not ok

    def test_neq_fails_on_equal(self):
        ok, _ = _evaluate_numeric_checks("!= 10", "value 10")
        assert not ok

    # --- Range (in) operator ---

    def test_in_range_passes(self):
        ok, _ = _evaluate_numeric_checks("in 10..30", "temp 20 C")
        assert ok

    def test_in_range_at_lower_bound_passes(self):
        ok, _ = _evaluate_numeric_checks("in 10..30", "temp 10 C")
        assert ok

    def test_in_range_at_upper_bound_passes(self):
        ok, _ = _evaluate_numeric_checks("in 10..30", "temp 30 C")
        assert ok

    def test_in_range_below_lower_fails(self):
        ok, failures = _evaluate_numeric_checks("in 10..30", "temp 5 C")
        assert not ok
        assert len(failures) == 1

    def test_in_range_above_upper_fails(self):
        ok, _ = _evaluate_numeric_checks("in 10..30", "temp 35 C")
        assert not ok

    # --- Prefix-based search ---

    def test_prefix_isolates_correct_number(self):
        # Response has two numbers; prefix should pick the right one
        ok, _ = _evaluate_numeric_checks("+CSQ: >= 5", "+CSQ: 15, noise 2")
        assert ok

    def test_prefix_not_found_fails(self):
        ok, failures = _evaluate_numeric_checks("+CSQ: >= 5", "no prefix here 15")
        assert not ok
        assert any("Prefix not found" in f for f in failures)

    def test_empty_prefix_uses_first_number(self):
        ok, _ = _evaluate_numeric_checks(">= 5", "result: 10")
        assert ok

    # --- No number found ---

    def test_no_number_in_response_fails(self):
        ok, failures = _evaluate_numeric_checks(">= 5", "no numbers here")
        assert not ok
        assert any("No number" in f for f in failures)

    def test_no_number_after_prefix_fails(self):
        ok, failures = _evaluate_numeric_checks("PREFIX: >= 5", "PREFIX: no digits")
        assert not ok
        assert any("No number" in f for f in failures)

    # --- Float values ---

    def test_float_value_in_response(self):
        ok, _ = _evaluate_numeric_checks(">= 1.5", "reading 2.5")
        assert ok

    def test_float_threshold(self):
        ok, _ = _evaluate_numeric_checks(">= 1.5", "reading 1.4")
        assert not ok

    def test_float_range(self):
        ok, _ = _evaluate_numeric_checks("in 15.0..35.0", "TEMP: 25.3")
        assert ok

    # --- Multiple checks ---

    def test_all_checks_pass(self):
        ok, _ = _evaluate_numeric_checks(">= 5\n<= 20", "value 10")
        assert ok

    def test_first_check_fails_reports_failure(self):
        ok, failures = _evaluate_numeric_checks(">= 50\n<= 100", "value 10")
        assert not ok
        assert len(failures) >= 1

    def test_second_check_fails(self):
        ok, failures = _evaluate_numeric_checks(">= 5\n<= 8", "value 10")
        assert not ok

    def test_blank_lines_between_checks_ignored(self):
        ok, _ = _evaluate_numeric_checks(">= 5\n\n<= 20", "value 10")
        assert ok

    # --- Syntax errors ---

    def test_bad_syntax_reports_failure(self):
        ok, failures = _evaluate_numeric_checks("not valid syntax at all", "10")
        assert not ok
        assert any("Bad syntax" in f for f in failures)

    def test_bad_range_format_reports_failure(self):
        ok, failures = _evaluate_numeric_checks("in 10-30", "value 15")
        assert not ok
        assert any("Bad range" in f for f in failures)

    def test_non_numeric_threshold_reports_failure(self):
        ok, failures = _evaluate_numeric_checks(">= abc", "value 10")
        assert not ok
        assert any("Non-numeric" in f for f in failures)

    def test_non_numeric_range_bounds_reports_failure(self):
        ok, failures = _evaluate_numeric_checks("in abc..def", "value 10")
        assert not ok
        assert any("Non-numeric" in f for f in failures)


# ---------------------------------------------------------------------------
# TestCase serialization
# ---------------------------------------------------------------------------

class TestTestCaseSerialization:
    def _make_case(self) -> TestCase:
        return TestCase(
            name="Signal Check",
            command="AT+CSQ",
            expected="CSQ",
            terminator="OK",
            timeout_ms=3000,
            enabled=True,
            manual=False,
            setup_commands=["AT", "AT+CMGF=1"],
            teardown_commands=["AT+CMGF=0"],
            nav_timeout_ms=500,
            numeric_checks="+CSQ: >= 5",
            trigger_commands=["TRIG"],
            trigger_timing="after_setup",
        )

    def test_to_dict_contains_all_fields(self):
        tc = self._make_case()
        d = tc.to_dict()
        for key in ("id", "name", "command", "expected", "terminator",
                    "timeout_ms", "enabled", "manual", "log_only",
                    "setup_commands", "teardown_commands", "nav_timeout_ms",
                    "numeric_checks", "trigger_commands", "trigger_timing"):
            assert key in d

    def test_to_dict_values_match(self):
        tc = self._make_case()
        d = tc.to_dict()
        assert d["name"] == "Signal Check"
        assert d["command"] == "AT+CSQ"
        assert d["timeout_ms"] == 3000
        assert d["setup_commands"] == ["AT", "AT+CMGF=1"]
        assert d["trigger_timing"] == "after_setup"

    def test_from_dict_roundtrip(self):
        tc = self._make_case()
        tc2 = TestCase.from_dict(tc.to_dict())
        assert tc2.name == tc.name
        assert tc2.command == tc.command
        assert tc2.expected == tc.expected
        assert tc2.terminator == tc.terminator
        assert tc2.timeout_ms == tc.timeout_ms
        assert tc2.setup_commands == tc.setup_commands
        assert tc2.teardown_commands == tc.teardown_commands
        assert tc2.numeric_checks == tc.numeric_checks
        assert tc2.trigger_commands == tc.trigger_commands
        assert tc2.trigger_timing == tc.trigger_timing
        assert tc2.id == tc.id

    def test_from_dict_empty_uses_defaults(self):
        tc = TestCase.from_dict({})
        assert tc.name == ""
        assert tc.command == ""
        assert tc.terminator == "OK"
        assert tc.timeout_ms == 2000
        assert tc.enabled is True
        assert tc.manual is False
        assert tc.log_only is False
        assert tc.setup_commands == []
        assert tc.teardown_commands == []
        assert tc.nav_timeout_ms == 1000
        assert tc.numeric_checks == ""
        assert tc.trigger_commands == []
        assert tc.trigger_timing == "before_setup"

    def test_from_dict_missing_id_generates_new_uuid(self):
        tc = TestCase.from_dict({"name": "test"})
        assert tc.id  # non-empty
        uuid.UUID(tc.id)  # valid UUID4 format

    def test_from_dict_preserves_existing_id(self):
        fixed_id = str(uuid.uuid4())
        tc = TestCase.from_dict({"id": fixed_id, "name": "x"})
        assert tc.id == fixed_id

    def test_default_id_is_valid_uuid(self):
        tc = TestCase(name="t", command="c", expected="e")
        uuid.UUID(tc.id)

    def test_each_instance_gets_unique_id(self):
        a = TestCase(name="a", command="", expected="")
        b = TestCase(name="b", command="", expected="")
        assert a.id != b.id


# ---------------------------------------------------------------------------
# FakeSerialHandler — drives TestRunner without real hardware
# ---------------------------------------------------------------------------

class FakeSerialHandler(SerialHandler):
    """A SerialHandler that injects pre-defined response lines into the
    capture queue when send() is called, without needing a real serial port."""

    def __init__(self, responses: list):
        super().__init__()
        self._responses = responses   # list of strings to inject
        self._fake_connected = True
        self._send_calls: list = []

    @property
    def is_connected(self) -> bool:
        return self._fake_connected

    def send(self, text: str, line_ending: bytes) -> None:
        self._send_calls.append(text)
        cq = self._capture_queue
        if cq is not None:
            for resp_text in self._responses:
                cq.put(TerminalMessage(Direction.RX, resp_text))


def _run_sync(runner: TestRunner, tests: list, handler: SerialHandler,
              line_ending: bytes = b"\r\n", delay_ms: int = 0,
              trigger_handler=None, on_manual_input=None) -> list:
    """Run tests and block until done; return collected TestResult list."""
    results = []
    done_event = threading.Event()

    def on_result(r):
        results.append(r)

    def on_done():
        done_event.set()

    runner.run(tests, handler, line_ending, on_result, on_done,
               delay_ms=delay_ms, trigger_handler=trigger_handler,
               on_manual_input=on_manual_input)
    done_event.wait(timeout=10.0)
    return results


# ---------------------------------------------------------------------------
# TestRunner — basic state
# ---------------------------------------------------------------------------

class TestTestRunnerState:
    def test_not_running_initially(self):
        runner = TestRunner()
        assert not runner.is_running

    def test_is_running_while_active(self):
        runner = TestRunner()
        handler = FakeSerialHandler(["OK"])
        tc = TestCase(name="t", command="cmd", expected="", terminator="OK", timeout_ms=2000)

        done = threading.Event()
        runner.run([tc], handler, b"\r\n",
                   on_result=lambda r: None,
                   on_done=lambda: done.set(),
                   delay_ms=0)
        # Give thread a moment to start
        time.sleep(0.05)
        assert runner.is_running or done.is_set()
        done.wait(timeout=5.0)

    def test_not_running_after_completion(self):
        runner = TestRunner()
        handler = FakeSerialHandler(["OK"])
        tc = TestCase(name="t", command="cmd", expected="", terminator="OK", timeout_ms=500)
        _run_sync(runner, [tc], handler)
        # Give thread a moment to finish
        time.sleep(0.1)
        assert not runner.is_running


# ---------------------------------------------------------------------------
# TestRunner — PASS / FAIL / TIMEOUT / ERROR
# ---------------------------------------------------------------------------

class TestTestRunnerResults:
    def test_pass_when_terminator_and_expected_found(self):
        handler = FakeSerialHandler(["result: CSQ 15", "OK"])
        tc = TestCase(name="t", command="AT+CSQ", expected="CSQ",
                      terminator="OK", timeout_ms=2000)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "PASS"

    def test_pass_with_no_expected_substring(self):
        handler = FakeSerialHandler(["OK"])
        tc = TestCase(name="t", command="AT", expected="",
                      terminator="OK", timeout_ms=2000)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "PASS"

    def test_fail_when_expected_substring_missing(self):
        handler = FakeSerialHandler(["garbage", "OK"])
        tc = TestCase(name="t", command="AT+CSQ", expected="CSQ",
                      terminator="OK", timeout_ms=2000)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "FAIL"

    def test_fail_when_numeric_check_fails(self):
        handler = FakeSerialHandler(["+CSQ: 2", "OK"])
        tc = TestCase(name="t", command="AT+CSQ", expected="",
                      terminator="OK", timeout_ms=2000,
                      numeric_checks="+CSQ: >= 10")
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "FAIL"

    def test_pass_when_numeric_check_passes(self):
        handler = FakeSerialHandler(["+CSQ: 20", "OK"])
        tc = TestCase(name="t", command="AT+CSQ", expected="",
                      terminator="OK", timeout_ms=2000,
                      numeric_checks="+CSQ: >= 10")
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "PASS"

    def test_timeout_when_terminator_not_received(self):
        handler = FakeSerialHandler(["no terminator here"])
        tc = TestCase(name="t", command="AT", expected="",
                      terminator="OK", timeout_ms=200)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "TIMEOUT"

    def test_error_when_not_connected(self):
        handler = FakeSerialHandler([])
        handler._fake_connected = False
        tc = TestCase(name="t", command="AT", expected="", terminator="OK")
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "ERROR"
        assert "Not connected" in results[0].actual

    def test_error_when_send_raises(self):
        import serial as pyserial

        class RaisingHandler(FakeSerialHandler):
            def send(self, text, line_ending):
                raise pyserial.SerialException("port gone")

        handler = RaisingHandler([])
        tc = TestCase(name="t", command="AT", expected="", terminator="OK")
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "ERROR"
        assert "Send failed" in results[0].actual

    def test_actual_contains_collected_lines(self):
        handler = FakeSerialHandler(["line1", "line2", "OK"])
        tc = TestCase(name="t", command="AT", expected="",
                      terminator="OK", timeout_ms=2000)
        results = _run_sync(TestRunner(), [tc], handler)
        assert "line1" in results[0].actual
        assert "line2" in results[0].actual

    def test_duration_ms_is_positive(self):
        handler = FakeSerialHandler(["OK"])
        tc = TestCase(name="t", command="AT", expected="", terminator="OK", timeout_ms=2000)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].duration_ms >= 0

    def test_multiple_expected_substrings_all_must_match(self):
        handler = FakeSerialHandler(["alpha", "beta", "OK"])
        tc = TestCase(name="t", command="cmd", expected="alpha\nbeta",
                      terminator="OK", timeout_ms=2000)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "PASS"

    def test_multiple_expected_one_missing_is_fail(self):
        handler = FakeSerialHandler(["alpha", "OK"])
        tc = TestCase(name="t", command="cmd", expected="alpha\nbeta",
                      terminator="OK", timeout_ms=2000)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "FAIL"


# ---------------------------------------------------------------------------
# TestRunner — multiple tests in sequence
# ---------------------------------------------------------------------------

class TestTestRunnerSequence:
    def test_all_tests_run_in_order(self):
        handler = FakeSerialHandler(["OK"])
        tests = [
            TestCase(name="a", command="cmd_a", expected="", terminator="OK", timeout_ms=500),
            TestCase(name="b", command="cmd_b", expected="", terminator="OK", timeout_ms=500),
            TestCase(name="c", command="cmd_c", expected="", terminator="OK", timeout_ms=500),
        ]
        results = _run_sync(TestRunner(), tests, handler, delay_ms=0)
        assert len(results) == 3
        assert [r.test.name for r in results] == ["a", "b", "c"]

    def test_on_done_called_after_all_tests(self):
        handler = FakeSerialHandler(["OK"])
        tests = [TestCase(name=str(i), command="cmd", expected="",
                          terminator="OK", timeout_ms=500) for i in range(3)]
        done_event = threading.Event()
        results = []

        TestRunner().run(tests, handler, b"\r\n",
                         on_result=lambda r: results.append(r),
                         on_done=lambda: done_event.set(),
                         delay_ms=0)
        done_event.wait(timeout=10.0)
        assert done_event.is_set()
        assert len(results) == 3

    def test_delay_between_tests(self):
        handler = FakeSerialHandler(["OK"])
        tests = [
            TestCase(name="a", command="cmd", expected="", terminator="OK", timeout_ms=500),
            TestCase(name="b", command="cmd", expected="", terminator="OK", timeout_ms=500),
        ]
        t_start = time.monotonic()
        _run_sync(TestRunner(), tests, handler, delay_ms=200)
        elapsed = time.monotonic() - t_start
        assert elapsed >= 0.2  # at least one 200 ms delay between tests


# ---------------------------------------------------------------------------
# TestRunner — stop mid-run
# ---------------------------------------------------------------------------

class TestTestRunnerStop:
    def test_stop_halts_remaining_tests(self):
        """If stop() is called before the runner starts the second test,
        the second test should not execute."""
        started = threading.Event()
        results = []
        done_event = threading.Event()

        class SlowHandler(FakeSerialHandler):
            def send(self, text, line_ending):
                started.set()
                # Pause long enough for stop() to be called
                time.sleep(0.3)
                super().send(text, line_ending)

        handler = SlowHandler(["OK"])
        tests = [
            TestCase(name="first", command="cmd", expected="", terminator="OK", timeout_ms=1000),
            TestCase(name="second", command="cmd", expected="", terminator="OK", timeout_ms=1000),
        ]
        runner = TestRunner()
        runner.run(tests, handler, b"\r\n",
                   on_result=lambda r: results.append(r),
                   on_done=lambda: done_event.set(),
                   delay_ms=0)

        started.wait(timeout=2.0)
        runner.stop()
        done_event.wait(timeout=5.0)

        names = [r.test.name for r in results]
        assert "second" not in names

    def test_on_done_called_after_stop(self):
        done_event = threading.Event()

        class SlowHandler(FakeSerialHandler):
            def send(self, text, line_ending):
                time.sleep(0.2)
                super().send(text, line_ending)

        handler = SlowHandler(["OK"])
        tests = [TestCase(name="t", command="cmd", expected="",
                          terminator="OK", timeout_ms=2000)]
        runner = TestRunner()
        runner.run(tests, handler, b"\r\n",
                   on_result=lambda r: None,
                   on_done=lambda: done_event.set(),
                   delay_ms=0)
        runner.stop()
        done_event.wait(timeout=5.0)
        assert done_event.is_set()


# ---------------------------------------------------------------------------
# TestRunner — TX echo goes to rx_queue
# ---------------------------------------------------------------------------

class TestTestRunnerTxEcho:
    def test_tx_message_put_in_rx_queue(self):
        handler = FakeSerialHandler(["OK"])
        tc = TestCase(name="t", command="AT+TEST", expected="",
                      terminator="OK", timeout_ms=2000)
        _run_sync(TestRunner(), [tc], handler)

        tx_msgs = []
        while not handler.rx_queue.empty():
            m = handler.rx_queue.get_nowait()
            if m.direction == Direction.TX:
                tx_msgs.append(m)
        assert any("AT+TEST" in m.text for m in tx_msgs)


# ---------------------------------------------------------------------------
# TestRunner — manual tests
# ---------------------------------------------------------------------------

class TestTestRunnerManual:
    def test_manual_test_uses_set_manual_result(self):
        handler = FakeSerialHandler([])
        tc = TestCase(name="manual", command="", expected="",
                      terminator="OK", timeout_ms=2000, manual=True)
        runner = TestRunner()

        def provide_verdict(test):
            # Simulate user clicking OK after a short pause
            threading.Timer(0.1, lambda: runner.set_manual_result("PASS", "looks good")).start()

        results = _run_sync(runner, [tc], handler, on_manual_input=provide_verdict)
        assert results[0].status == "PASS"
        assert results[0].actual == "looks good"

    def test_manual_fail_verdict(self):
        handler = FakeSerialHandler([])
        tc = TestCase(name="m", command="", expected="",
                      terminator="OK", timeout_ms=2000, manual=True)
        runner = TestRunner()

        def provide_verdict(test):
            threading.Timer(0.1, lambda: runner.set_manual_result("FAIL", "wrong output")).start()

        results = _run_sync(runner, [tc], handler, on_manual_input=provide_verdict)
        assert results[0].status == "FAIL"
        assert results[0].actual == "wrong output"

    def test_manual_test_stopped_mid_wait_returns_error(self):
        handler = FakeSerialHandler([])
        tc = TestCase(name="m", command="", expected="",
                      terminator="OK", timeout_ms=2000, manual=True)
        runner = TestRunner()

        # Stop the runner before verdict is given
        def stop_runner(test):
            threading.Timer(0.1, runner.stop).start()

        results = _run_sync(runner, [tc], handler, on_manual_input=stop_runner)
        assert results[0].status == "ERROR"

    def test_set_manual_result_sets_event(self):
        runner = TestRunner()
        runner._manual_event.clear()
        runner.set_manual_result("PASS", "ok")
        assert runner._manual_event.is_set()
        assert runner._manual_result == ("PASS", "ok")


# ---------------------------------------------------------------------------
# TestRunner — trigger commands
# ---------------------------------------------------------------------------

class TestTestRunnerTrigger:
    def test_trigger_commands_sent_to_trigger_handler(self):
        handler = FakeSerialHandler(["OK"])
        trigger = FakeSerialHandler([])
        tc = TestCase(name="t", command="cmd", expected="",
                      terminator="OK", timeout_ms=2000,
                      trigger_commands=["TRIG_CMD"],
                      trigger_timing="before_setup")
        _run_sync(TestRunner(), [tc], handler, trigger_handler=trigger)
        assert "TRIG_CMD" in trigger._send_calls

    def test_no_trigger_handler_does_not_crash(self):
        handler = FakeSerialHandler(["OK"])
        tc = TestCase(name="t", command="cmd", expected="",
                      terminator="OK", timeout_ms=2000,
                      trigger_commands=["TRIG"])
        results = _run_sync(TestRunner(), [tc], handler, trigger_handler=None)
        assert results[0].status == "PASS"

    def test_trigger_not_sent_when_disconnected(self):
        handler = FakeSerialHandler(["OK"])
        trigger = FakeSerialHandler([])
        trigger._fake_connected = False
        tc = TestCase(name="t", command="cmd", expected="",
                      terminator="OK", timeout_ms=2000,
                      trigger_commands=["TRIG"])
        _run_sync(TestRunner(), [tc], handler, trigger_handler=trigger)
        assert trigger._send_calls == []


# ---------------------------------------------------------------------------
# TestRunner — log_only tests
# ---------------------------------------------------------------------------

class TestTestRunnerLogOnly:
    def test_log_only_returns_log_status(self):
        handler = FakeSerialHandler(["data line", "OK"])
        tc = TestCase(name="t", command="AT+LOG", expected="",
                      terminator="OK", timeout_ms=2000, log_only=True)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "LOG"

    def test_log_only_captures_response(self):
        handler = FakeSerialHandler(["data line", "OK"])
        tc = TestCase(name="t", command="AT+LOG", expected="",
                      terminator="OK", timeout_ms=2000, log_only=True)
        results = _run_sync(TestRunner(), [tc], handler)
        assert "data line" in results[0].actual
        assert "OK" in results[0].actual

    def test_log_only_returns_log_even_without_terminator(self):
        # Even if the terminator is never received, log_only returns LOG not TIMEOUT
        handler = FakeSerialHandler(["some data"])
        tc = TestCase(name="t", command="AT+LOG", expected="",
                      terminator="OK", timeout_ms=200, log_only=True)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "LOG"

    def test_log_only_skips_expected_evaluation(self):
        # expected substring would cause PASS but log_only returns LOG
        handler = FakeSerialHandler(["expected_string", "OK"])
        tc = TestCase(name="t", command="AT+LOG", expected="expected_string",
                      terminator="OK", timeout_ms=2000, log_only=True)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "LOG"

    def test_log_only_skips_numeric_checks(self):
        # numeric check would fail but log_only returns LOG not FAIL
        handler = FakeSerialHandler(["+VAL: 1", "OK"])
        tc = TestCase(name="t", command="AT+VAL", expected="",
                      terminator="OK", timeout_ms=2000,
                      numeric_checks="+VAL: >= 100",
                      log_only=True)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "LOG"

    def test_log_only_serialization_roundtrip(self):
        tc = TestCase(name="t", command="cmd", expected="", log_only=True)
        tc2 = TestCase.from_dict(tc.to_dict())
        assert tc2.log_only is True

    def test_log_only_defaults_to_false(self):
        tc = TestCase.from_dict({})
        assert tc.log_only is False

    def test_log_only_false_still_evaluates(self):
        # Sanity: log_only=False with missing expected → FAIL, not LOG
        handler = FakeSerialHandler(["no match", "OK"])
        tc = TestCase(name="t", command="cmd", expected="expected",
                      terminator="OK", timeout_ms=2000, log_only=False)
        results = _run_sync(TestRunner(), [tc], handler)
        assert results[0].status == "FAIL"
