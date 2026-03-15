# Serial Terminal GUI

A Tkinter desktop application for manually and automatically testing embedded systems over a serial (UART/USB-CDC) connection. Devices use a text/ASCII protocol (AT-style commands with newline-terminated responses).

## Quick start

```
pip install pyserial
python main.py
```

## Features

- **Multiple terminals** — open up to 4 independent terminal panes side by side (＋ Add Terminal / － Remove Terminal); each has its own port, log file, and session
- **Terminal tab** — manual serial TX/RX with colour-coded output, timestamps, and session logging per pane
- **Test Suite tab** — automated test cases with expected response matching, numeric checks, setup/teardown navigation commands, loop mode, and CSV export
- **Multiple independent suites** — open up to 4 independent suite panes (＋ Add Suite / － Remove Suite); each connects to its own device and runs in parallel
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
| Config defaults, load, save, migration | `app/config.py` | `DEFAULTS`, `TERMINAL_DEFAULTS`, `AppConfig` |
| Per-terminal config slice helpers | `app/config.py` | `AppConfig.get_terminal_config()`, `save_terminal_config()`, `set_terminal_count()` |
| Main window layout, terminal add/remove, Test Suite tab | `app/gui/main_window.py` | `MainWindow` |
| Self-contained terminal pane (own handler + poll loop) | `app/gui/terminal_pane.py` | `TerminalPane`, `TerminalConfigProxy` |
| Port / baud / parity / line-ending / log-folder controls | `app/gui/connection_panel.py` | `ConnectionPanel` |
| Terminal display widget | `app/gui/terminal_panel.py` | `TerminalPanel.batch_append()` |
| Command entry, history, special-char buttons | `app/gui/command_panel.py` | `CommandPanel` |
| Test suite UI — all of it | `app/gui/test_suite_panel.py` | `TestSuitePanel` |
| Suite device connection (per-suite) | `app/gui/test_suite_panel.py` | `_on_suite_connect_click()`, `_poll_suite_queue()` |
| Test CRUD dialogs | `app/gui/test_suite_panel.py` | `_open_test_dialog()` |
| Run control, loop, CSV writing | `app/gui/test_suite_panel.py` | `_start_run()`, `_on_done()` |

## Architecture in one paragraph

`MainWindow` manages a list of `TerminalPane` instances arranged in a horizontal `ttk.PanedWindow`. Each `TerminalPane` owns its own `SerialHandler`, `SessionLogger`, and `after()`-based poll loop — up to 4 panes can run simultaneously on different ports. `TerminalConfigProxy` bridges `ConnectionPanel`'s flat config interface to the per-pane slice stored under `config_1.json → terminals[i]`. Each `TestSuitePanel` similarly owns an independent `SerialHandler` (`_suite_handler`) with its own poll loop, displaying output in a compact mini-log. `TestRunner` executes in a daemon thread; all results come back via `root.after(0, callback)` — no Tkinter calls from threads. All inter-thread data flows through `queue.Queue`. Terminal panes and suite panels share no state and can run concurrently.

## Running tests

```
pip install pytest
python -m pytest
```

185 tests across 4 files — no hardware required (serial I/O is mocked):

| File | What it covers |
|------|----------------|
| `tests/test_config.py` | `AppConfig` load/save, config migration, terminal config helpers, log-dir resolution |
| `tests/test_serial_handler.py` | `SerialHandler` state, capture mode, read-loop byte splitting, error handling |
| `tests/test_logger.py` | `SessionLogger` open/write/close lifecycle, file naming, log line format |
| `tests/test_runner.py` | Numeric checks (all operators), `TestCase` serialisation, `TestRunner` PASS/FAIL/TIMEOUT/ERROR/stop/manual/trigger |

## Config files

| File | Purpose |
|------|---------|
| `config_1.json` | Terminal pane settings, Suite 1 tests, app display settings, open suite count |
| `config_2.json` | Suite 2 connection settings and tests |
| `config_3.json` | Suite 3 connection settings and tests |
| `config_4.json` | Suite 4 connection settings and tests |

All files are auto-created on first run and are excluded from version control (`.gitignore`). Missing keys are filled from `DEFAULTS` in `app/config.py` automatically. Old flat-key terminal configs and `suite_2_visible` are automatically migrated on first launch.
