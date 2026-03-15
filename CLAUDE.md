# Serial Terminal GUI — Project Context

## What this is

A Tkinter desktop application for manually and automatically testing embedded systems over a serial (UART/USB-CDC) connection. The target device uses a text/ASCII protocol (AT-style commands with newline-terminated responses).

Run with:
```
pip install pyserial
python main.py
```

Run tests with:
```
pip install pytest
python -m pytest
```

## File structure

```
SerialTerminalGUI/
├── main.py                        # Entry point only — DPI fix, load config, start Tk
├── requirements.txt               # pyserial>=3.5 (only external dependency)
├── pytest.ini                     # Test config — testpaths=tests, norecursedirs=app lib
├── tests/
│   ├── test_config.py             # AppConfig: load, save, migration, terminal helpers
│   ├── test_serial_handler.py     # SerialHandler: state, capture mode, read loop
│   ├── test_logger.py             # SessionLogger: lifecycle, file naming, write format
│   └── test_runner.py             # Numeric checks, TestCase serialisation, TestRunner execution
└── app/
    ├── config.py                  # Constants (BAUD_RATES, LINE_ENDINGS, PARITIES…) + JSON persistence
    ├── serial_handler.py          # PySerial wrapper + threaded reader + capture mode
    ├── logger.py                  # Session file logging to configurable log dir
    ├── test_runner.py             # TestCase / TestResult dataclasses + TestRunner thread
    └── gui/
        ├── main_window.py         # Integration hub — manages list of TerminalPane + Test Suite tab
        ├── terminal_pane.py       # Self-contained terminal (ConnectionPanel + TerminalPanel + CommandPanel + own handler)
        ├── connection_panel.py    # Port / baud / parity / line-ending controls + log folder selector
        ├── terminal_panel.py      # Dark scrolled terminal with colour-coded TX/RX
        ├── command_panel.py       # Command entry + Up/Down history + special-char buttons (ESC/TAB/^C)
        └── test_suite_panel.py   # Test CRUD, treeview, runner; owns its own SerialHandler per suite
```

## Architecture — key decisions

### Threading model
- Each `SerialHandler` instance runs one daemon reader thread (`_read_loop`) that reads bytes from the port and splits on `\n`.
- The reader thread **only** calls `queue.put()` — it never touches any Tkinter object.
- Each `TerminalPane` runs its own `_poll_queue()` loop every 50 ms via `self.after()`, draining its handler's `rx_queue` into its `TerminalPanel` and `SessionLogger`. Up to 4 loops run simultaneously (one per open terminal pane).
- Each `TestSuitePanel` runs its own `_poll_suite_queue()` loop (also 50 ms) draining its suite handler's `rx_queue` into the per-suite mini-log widget. This loop starts at widget creation and runs forever (idle when disconnected).
- The `after()` poll loops are **never cancelled** — they run even when disconnected (queues are just empty). When a `TerminalPane` widget is destroyed (terminal removed), Tk automatically cancels its pending `after` callbacks.

### TX echo
TX commands are **not** read back from the serial port. Instead `_on_send_request` (in `TerminalPane`) immediately puts a `TerminalMessage(Direction.TX, text)` into `rx_queue` before calling `handler.send()`. This gives instant feedback and avoids half-duplex echo issues. Suite test commands are not echoed to the terminal (they go only to the capture queue).

### Automated test runner
- `TestRunner` runs in its own daemon thread and communicates results back via `root.after(0, callback)` — never calls widget methods directly.
- **Capture mode**: before sending a test command `handler.start_capture()` creates a secondary `_capture_queue`. The reader thread writes every incoming message to both `rx_queue` (suite mini-log) and `_capture_queue` (test runner). After the test `handler.stop_capture()` sets `_capture_queue = None`.
- **Silent navigation commands** (`setup_commands` / `teardown_commands` on `TestCase`): sent via `_execute_silent()` which uses capture mode but **never puts anything into `rx_queue`**. This means menu-navigation steps are invisible in the mini-log and absent from the session log.
- **Escape expansion**: the token `<ESC>` in setup/teardown/trigger command strings is replaced with `\x1b` before sending, allowing control-character navigation.
- **Trigger device**: a secondary `SerialHandler` (`_trigger_handler`) owned by `TestSuitePanel`. When connected, `TestRunner.run()` receives it as `trigger_handler`. Before or after setup commands (controlled by `trigger_timing`), the runner calls `_run_trigger_commands()` which fires each `trigger_command` to the trigger port as fire-and-forget (no capture, no response wait, errors silently swallowed). The trigger handler is disconnected in `TestSuitePanel.cleanup()` on window close.
- **Manual tests** (`manual=True` on `TestCase`): the runner sends the command (if any), then calls `on_manual_input(test)` — a callback scheduled via `root.after(0, …)` — which opens a non-modal verdict dialog in the GUI. The runner thread blocks in a 50 ms polling loop on `_manual_event`, also checking `_stop_event` each tick. When the user clicks OK, `TestSuitePanel` calls `TestRunner.set_manual_result(status, actual)` which stores the result and sets `_manual_event`, unblocking the runner. Capture mode is **not** used for manual tests.

### Multiple independent terminals
- The Terminal tab contains up to **4 independent terminal panes**, each in its own column inside a horizontal `ttk.PanedWindow`.
- `＋ Add Terminal` / `－ Remove Terminal` buttons in the toolbar at the top of the Terminal tab add or remove the rightmost pane. Terminal 1 always exists; the buttons disable at the limits (1 and 4).
- Each pane is a `TerminalPane` widget (`app/gui/terminal_pane.py`) that owns its own `SerialHandler`, `SessionLogger`, `ConnectionPanel`, `TerminalPanel`, and `CommandPanel`. Panes are fully independent and can connect to different ports simultaneously.
- `MainWindow` keeps a `_panes: list` of `TerminalPane` instances and delegates all connection, send, and log management to each pane.
- `TerminalConfigProxy` (defined in `terminal_pane.py`) wraps `AppConfig` + a terminal index so that `ConnectionPanel` reads and writes `config_1.json → terminals[index]` rather than the root config. Non-terminal keys (autoscroll, font_size, etc.) fall through to the shared app config.
- When a terminal is removed, `pane.cleanup()` disconnects the handler and closes the logger before the widget is destroyed.

### Multiple independent suites
- The Test Suite tab contains up to **4 independent suite panes** in a horizontal `ttk.PanedWindow`, managed the same way as terminal panes.
- `＋ Add Suite` / `－ Remove Suite` buttons in the toolbar add or remove the rightmost pane. Suite 1 always exists; the buttons disable at the limits (1 and 4).
- `MainWindow` keeps `_suite_panels: list[TestSuitePanel]` and `_suite_configs: list[AppConfig]`. Suite 1 shares `self._config` (`config_1.json`); Suites 2–4 get their own `AppConfig` instances loaded from `config_2.json` / `config_3.json` / `config_4.json` on demand.
- `suite_count` in `config_1.json` persists how many suites were open. Migrated from the old `suite_2_visible` boolean on first launch.
- Each `TestSuitePanel` **owns** its own `SerialHandler` (`self._suite_handler`). Suite panels have their own **Device Connection** section and can connect to different ports and **run in parallel** — there is no interlock.
- The suite handler's `rx_queue` is drained by `_poll_suite_queue()` into a 3-line `tk.Text` mini-log widget at the top of the suite tab. ERROR messages from the reader thread trigger `_handle_suite_error_disconnect()` which disconnects and stops the runner.
- `cleanup()` on each `TestSuitePanel` disconnects both `_suite_handler` and `_trigger_handler`, and calls `_runner.stop()`.

### Config persistence
- `config_1.json` stores terminal pane settings, Suite 1 test state, app-level display settings, and `suite_count`. `config_2.json` / `config_3.json` / `config_4.json` store Suite 2–4 state and are only created when those suites are opened.
- Legacy `config.json` is auto-migrated to `config_1.json` on first launch.
- Old flat terminal keys (`port`, `baud`, etc.) are one-time migrated into `terminals[0]`; old `suite_2_visible` is migrated to `suite_count` (1 or 2) on first launch.
- Config files are in `.gitignore` — they are machine-specific.
- Config is saved on every successful connect (terminal or suite or trigger), when the log folder changes, when terminals or suites are added/removed, and on clean shutdown.
- `terminals` key in `config_1.json`: a list of per-terminal dicts, one entry per open terminal pane. Schema defined by `TERMINAL_DEFAULTS` in `config.py`. `AppConfig.get_terminal_config(i)` / `save_terminal_config(i, values)` / `set_terminal_count(n)` manage this list.
- `suite_count` key in `config_1.json`: integer 1–4, number of suite panes to restore on launch.
- `log_dir` inside each terminal dict: empty string means `~/serial_logs`. `AppConfig.effective_log_dir_for(terminal_cfg)` resolves it.
- Suite-specific connection keys (per suite config): `suite_port`, `suite_baud`, `suite_parity`, `suite_line_ending`.
- `trigger_port` / `trigger_baud`: last-used trigger device port and baud rate (saved when trigger connects).

### CSV output files
Two CSV files are written to each suite's configured log folder on each test run:

| File | Written | Format |
|------|---------|--------|
| `test_run_<timestamp>.csv` | Created at run start, one wide-format row appended per loop iteration | Columns: `Run_Start`, `Run_End`, then `<name>_Status` + `<name>_Actual` for every test in the suite |
| `test_suite_log.csv` | One row appended per run completion | Columns: `Timestamp`, then one column per test name (value = status or blank if not in this run) |

In loop mode the per-run CSV accumulates one row per iteration; a new file is only created when a fresh run starts (i.e. after a non-looping run ends or Stop is pressed).

## GUI layout

```
ttk.Notebook
├── Tab 1 "Terminal"
│   ├── Toolbar   [＋ Add Terminal]  [－ Remove Terminal]   (max 4 panes)
│   └── ttk.PanedWindow (horizontal, holds 1–4 TerminalPane columns)
│       └── Each TerminalPane contains:
│           ├── ConnectionPanel  (Port / Refresh / Baud / Parity / Data bits / Stop bits / Line ending / Log folder)
│           │                    [Connect]  [Browse…]
│           ├── TerminalPanel    (dark ScrolledText, expands)
│           ├── CommandPanel     (entry + send + history + [ESC] [TAB] [^C])
│           └── Status bar       (connection info left  |  log file path right)
└── Tab 2 "Test Suite"
    ├── Toolbar   [＋ Add Suite]  [－ Remove Suite]   (max 4 panes)
    └── ttk.PanedWindow (horizontal, holds 1–4 TestSuitePanel columns)
        └── Each suite pane (TestSuitePanel) contains:
            ├── Device Connection  (Port / Refresh / Baud / Line ending / [Connect Device])
            │                      (mini 3-line connection log)
            │                      (Log folder entry / [Browse…])
            ├── Trigger Device     (Port / Refresh / Baud / [Connect Trigger])
            ├── Toolbar            (Add / Edit / Delete / Up / Down)
            ├── Treeview           (✓ | ⚙ | Name | Command | Expected | Terminator | Timeout | Result)
            ├── Run bar            (Run Selected / Run All / Stop / ↻ Loop / loop interval spinbox / delay spinbox)
            ├── Results panel      (ScrolledText with coloured background boxes per result)
            └── Summary bar        (pass count / Export CSV… / Clear Results)
```

## Terminal colour scheme

| Direction | Colour    |
|-----------|-----------|
| TX        | `#00BFFF` (sky blue) |
| RX        | `#00FF7F` (spring green) |
| INFO      | `#FFD700` (gold) |
| ERROR     | `#FF4444` (red) |

The same colour scheme is used for the per-suite mini connection log.

## Test result colours

Used in both the Treeview row foreground and the results panel background boxes.

| Status  | Row fg    | Box bg    | Box fg    |
|---------|-----------|-----------|-----------|
| PASS    | `#00FF7F` | `#0D3B1F` | `#00FF7F` |
| FAIL    | `#FF5555` | `#3B0D0D` | `#FF5555` |
| TIMEOUT | `#FFD700` | `#3B2D00` | `#FFD700` |
| ERROR   | `#FF9100` | `#3B1A00` | `#FF9100` |

## TestCase fields

| Field              | Default | Notes |
|--------------------|---------|-------|
| `name`             | —       | Display name |
| `command`          | —       | Sent to device; echoed in terminal |
| `expected`         | `""`    | Newline-separated substrings; **all** must appear in the response |
| `terminator`       | `"OK"`  | Line that signals end of response |
| `timeout_ms`       | `2000`  | Timeout waiting for terminator |
| `numeric_checks`   | `""`    | Newline-separated numeric assertions (see format below) |
| `setup_commands`   | `[]`            | Navigation commands sent **silently** before the test |
| `teardown_commands`| `[]`            | Navigation commands sent **silently** after the test |
| `nav_timeout_ms`   | `1000`          | Per-step timeout for each silent navigation command |
| `trigger_commands` | `[]`            | Commands sent fire-and-forget to the trigger port (no response waited) |
| `trigger_timing`   | `"before_setup"`| When to fire trigger: `"before_setup"` or `"after_setup"` |
| `manual`           | `False`         | If `True`, runner pauses after sending the command and shows a dialog asking the user to choose PASS/FAIL and enter the actual response |
| `enabled`          | `True`          | Included in "Run All" when checked |
| `id`               | uuid4           | Stable identifier used as Treeview iid |

### Numeric check syntax

Each non-empty line in `numeric_checks` must follow one of:

```
<prefix> <op> <value>      # e.g.   +CSQ: >= 5
<prefix> in <lo>..<hi>     # e.g.   TEMP: in 15.0..35.0
```

- `prefix` (may be empty) is searched literally in the response; the first number found after it is extracted.
- `op` is one of `>= <= > < == !=`.
- Both patterns and numeric checks must pass for a result of PASS; failures are appended to the `actual` field.

### Pass/fail logic

For automated tests, a result is **PASS** only when **all** of the following hold:
1. The terminator line is received within `timeout_ms`.
2. Every non-empty line in `expected` appears as a substring of the response.
3. Every line in `numeric_checks` evaluates to true.

For **manual tests** (`manual=True`), the logic above is skipped entirely — the status and actual response come directly from the user's dialog input.

## Unit tests

Tests live in `tests/` and require only `pytest` (no hardware). Run with `python -m pytest`.

| File | Module under test | Key scenarios |
|------|-------------------|---------------|
| `tests/test_config.py` | `app/config.py` | Load/save round-trip, flat-key migration, `suite_2_visible` migration, `get_terminal_config` copy semantics, `set_terminal_count`, `effective_log_dir` |
| `tests/test_serial_handler.py` | `app/serial_handler.py` | `TerminalMessage` immutability, `is_connected` state, capture mode queue lifecycle, `send()` raises when disconnected, `_read_loop` via mock serial (line splitting, CR stripping, capture fan-out, error handling, UTF-8 replacement) |
| `tests/test_logger.py` | `app/logger.py` | `open_session` creates file with correct name pattern, `write` format (ISO timestamp + direction + text), `close_session` resets state, all no-op safety paths |
| `tests/test_runner.py` | `app/test_runner.py` | `_expand_escapes`, all 6 numeric operators + range + prefix + error cases, `TestCase` to/from dict round-trip, `TestRunner` PASS / FAIL / TIMEOUT / ERROR / stop mid-run / manual verdict / trigger dispatch |

### Testing approach — no real serial port needed
`FakeSerialHandler` (in `test_runner.py`) subclasses `SerialHandler`, overrides `is_connected` and `send()`. When `send()` is called it injects pre-defined response lines directly into `_capture_queue`, bypassing the read thread entirely. The read loop is tested separately in `test_serial_handler.py` via a `MagicMock` serial object whose `read()` side-effect feeds byte chunks on demand.

GUI modules (`main_window.py`, `terminal_pane.py`, `connection_panel.py`, `terminal_panel.py`, `command_panel.py`, `test_suite_panel.py`) are not unit-tested — they require a Tk event loop and real widget construction. All non-trivial logic in those files delegates to the tested modules above.

## Conventions

- All inter-thread communication goes through `queue.Queue` — no shared mutable state.
- `TerminalPane` wires its own callbacks internally (`_wire_callbacks`). `MainWindow` has no connect/send/disconnect logic — it only manages which panes exist.
- `TerminalConfigProxy` (in `terminal_pane.py`) is the bridge between a flat config-like interface (expected by `ConnectionPanel`) and the per-terminal slice in `AppConfig.terminals[i]`. It must cover every `self._config` call made by `ConnectionPanel`, `TerminalPanel`, and `CommandPanel`.
- `TestSuitePanel` owns its `SerialHandler` directly (`self._suite_handler`). There is no `handler_provider` lambda — the suite panel creates, connects, and disconnects its own handler.
- `_result_map: dict[test_id → (label, status)]` in `TestSuitePanel` persists results across tree repopulations (e.g. after reorder), and is cleared by "Clear Results" or at the start of each new run.
- `_current_csv_path` in `TestSuitePanel` tracks the active per-run CSV across loop iterations; it is set to `None` when a non-looping run finishes or Stop is pressed, causing the next run to open a fresh file.
- **Loop interval**: when "↻ Loop" is active and the interval spinbox is > 0, `_on_done` calls `_start_loop_countdown(seconds)` instead of restarting immediately. `_tick_loop_countdown` reschedules itself every 1 s via `self.after(1000, …)`, stores the `after()` ID in `_loop_after_id`, and updates the summary bar with "next run in Xs". When the countdown reaches 0 it calls `_start_run`. Clicking Stop during a countdown cancels the pending `after()` call and re-enables the run buttons immediately.
- The Treeview nav column shows `M` when `manual=True`, `⚙` when setup/teardown/trigger commands are present, and `M⚙` when both apply.
- `CommandPanel` special-char buttons (ESC / TAB / ^C) send a single control character with **no** line ending appended, using `on_send(char, b"")`.
