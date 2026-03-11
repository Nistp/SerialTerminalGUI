# Serial Terminal GUI

A Tkinter desktop application for manually and automatically testing embedded systems over a serial (UART/USB-CDC) connection. Devices use a text/ASCII protocol (AT-style commands with newline-terminated responses).

## Quick start

```
pip install pyserial
python main.py
```

## Features

- **Terminal tab** — manual serial TX/RX with colour-coded output and session logging
- **Test Suite tab** — automated test cases with expected response matching, numeric checks, setup/teardown navigation commands, loop mode, and CSV export
- **Multiple independent suites** — add a second suite pane (＋ Add Suite 2) to connect two devices simultaneously and run both test suites in parallel
- **Trigger device** — fire fire-and-forget commands to a separate port before/after each test (e.g. to simulate external events)
- **Manual verdict** — pause a run and ask the user to confirm a pass/fail (for tests requiring physical observation)

## Code map — where to look for what

| Goal | File | Key symbol |
|------|------|------------|
| App entry, DPI fix, config loading | `main.py` | `main()` |
| Serial port open/close, read thread, capture mode | `app/serial_handler.py` | `SerialHandler` |
| Test execution logic (setup, send, wait, evaluate) | `app/test_runner.py` | `TestRunner.run()`, `_execute_test()` |
| Test case data model and serialisation | `app/test_runner.py` | `TestCase`, `TestResult` dataclasses |
| Numeric check parsing and evaluation | `app/test_runner.py` | `_evaluate_numeric_checks()` |
| Session log file management | `app/logger.py` | `SessionLogger` |
| Config defaults, load, save, migration | `app/config.py` | `DEFAULTS`, `AppConfig` |
| Main window layout, terminal poll loop, connect/disconnect | `app/gui/main_window.py` | `MainWindow` |
| Top connection panel (Terminal tab) | `app/gui/connection_panel.py` | `ConnectionPanel` |
| Terminal display widget | `app/gui/terminal_panel.py` | `TerminalPanel.batch_append()` |
| Command entry, history, special-char buttons | `app/gui/command_panel.py` | `CommandPanel` |
| Test suite UI — all of it | `app/gui/test_suite_panel.py` | `TestSuitePanel` |
| Suite device connection (per-suite) | `app/gui/test_suite_panel.py` | `_on_suite_connect_click()`, `_poll_suite_queue()` |
| Test CRUD dialogs | `app/gui/test_suite_panel.py` | `_open_test_dialog()` |
| Run control, loop, CSV writing | `app/gui/test_suite_panel.py` | `_start_run()`, `_on_done()` |

## Architecture in one paragraph

`MainWindow` owns the **main terminal** `SerialHandler` and a `SessionLogger`. It polls `rx_queue` every 50 ms via `root.after()` and feeds messages to `TerminalPanel` and the logger. Each `TestSuitePanel` owns its own **independent** `SerialHandler` (`_suite_handler`) and polls its own `rx_queue` the same way, displaying output in a compact mini-log. `TestRunner` executes in a daemon thread; all results come back via `root.after(0, callback)` — no Tkinter calls from threads. All inter-thread data flows through `queue.Queue`. The two suite panels share no state and can run concurrently on different serial ports.

## Config files

| File | Purpose |
|------|---------|
| `config_1.json` | Suite 1 connection settings, tests, log folder, Suite 2 visibility |
| `config_2.json` | Suite 2 connection settings and tests |

Both files are auto-created on first run and are excluded from version control (`.gitignore`). Missing keys are filled from `DEFAULTS` in `app/config.py` automatically, so adding new config keys is backward-compatible.
