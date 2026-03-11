# Serial Terminal GUI — Project Context

## What this is

A Tkinter desktop application for manually and automatically testing embedded systems over a serial (UART/USB-CDC) connection. The target device uses a text/ASCII protocol (AT-style commands with newline-terminated responses).

Run with:
```
pip install pyserial
python main.py
```

## File structure

```
SerialTerminalGUI/
├── main.py                        # Entry point only — DPI fix, load config, start Tk
├── requirements.txt               # pyserial>=3.5 (only external dependency)
└── app/
    ├── config.py                  # Constants (BAUD_RATES, LINE_ENDINGS, PARITIES…) + JSON persistence
    ├── serial_handler.py          # PySerial wrapper + threaded reader + capture mode
    ├── logger.py                  # Session file logging to configurable log dir
    ├── test_runner.py             # TestCase / TestResult dataclasses + TestRunner thread
    └── gui/
        ├── main_window.py         # Integration hub — owns main terminal handler, logger, poll loop
        ├── connection_panel.py    # Port / baud / parity / line-ending controls + log folder (Terminal tab only)
        ├── terminal_panel.py      # Dark scrolled terminal with colour-coded TX/RX
        ├── command_panel.py       # Command entry + Up/Down history + special-char buttons (ESC/TAB/^C)
        └── test_suite_panel.py   # Test CRUD, treeview, runner; owns its own SerialHandler per suite
```

## Architecture — key decisions

### Threading model
- Each `SerialHandler` instance runs one daemon reader thread (`_read_loop`) that reads bytes from the port and splits on `\n`.
- The reader thread **only** calls `queue.put()` — it never touches any Tkinter object.
- `MainWindow._poll_queue()` drains the **main terminal handler's** `rx_queue` every 50 ms via `root.after()`, calling `terminal_panel.batch_append()` and `logger.write()`.
- Each `TestSuitePanel` runs its own `_poll_suite_queue()` loop (also 50 ms) draining its own suite handler's `rx_queue` into the per-suite mini-log widget. This loop starts at widget creation and runs forever (idle when disconnected).
- The `after()` poll loops are **never cancelled** — they run even when disconnected (queues are just empty).

### TX echo
TX commands are **not** read back from the serial port. Instead `_on_send_request` (in `MainWindow`) immediately puts a `TerminalMessage(Direction.TX, text)` into `rx_queue` before calling `handler.send()`. This gives instant feedback and avoids half-duplex echo issues. Suite test commands are not echoed to the terminal (they go only to the capture queue).

### Automated test runner
- `TestRunner` runs in its own daemon thread and communicates results back via `root.after(0, callback)` — never calls widget methods directly.
- **Capture mode**: before sending a test command `handler.start_capture()` creates a secondary `_capture_queue`. The reader thread writes every incoming message to both `rx_queue` (suite mini-log) and `_capture_queue` (test runner). After the test `handler.stop_capture()` sets `_capture_queue = None`.
- **Silent navigation commands** (`setup_commands` / `teardown_commands` on `TestCase`): sent via `_execute_silent()` which uses capture mode but **never puts anything into `rx_queue`**. This means menu-navigation steps are invisible in the mini-log and absent from the session log.
- **Escape expansion**: the token `<ESC>` in setup/teardown/trigger command strings is replaced with `\x1b` before sending, allowing control-character navigation.
- **Trigger device**: a secondary `SerialHandler` (`_trigger_handler`) owned by `TestSuitePanel`. When connected, `TestRunner.run()` receives it as `trigger_handler`. Before or after setup commands (controlled by `trigger_timing`), the runner calls `_run_trigger_commands()` which fires each `trigger_command` to the trigger port as fire-and-forget (no capture, no response wait, errors silently swallowed). The trigger handler is disconnected in `TestSuitePanel.cleanup()` on window close.
- **Manual tests** (`manual=True` on `TestCase`): the runner sends the command (if any), then calls `on_manual_input(test)` — a callback scheduled via `root.after(0, …)` — which opens a non-modal verdict dialog in the GUI. The runner thread blocks in a 50 ms polling loop on `_manual_event`, also checking `_stop_event` each tick. When the user clicks OK, `TestSuitePanel` calls `TestRunner.set_manual_result(status, actual)` which stores the result and sets `_manual_event`, unblocking the runner. Capture mode is **not** used for manual tests.

### Per-suite serial connections (independent)
- Each `TestSuitePanel` **owns** its own `SerialHandler` (`self._suite_handler`). This is entirely separate from the main terminal handler owned by `MainWindow`.
- The main `ConnectionPanel` (Terminal tab) controls only the main terminal connection. Suite panels have their own **Device Connection** section with port/baud/line-ending controls and a mini connection log.
- Suites can connect to different ports and **run in parallel** — there is no interlock.
- The suite handler's `rx_queue` is drained by `_poll_suite_queue()` into a 3-line `tk.Text` mini-log widget at the top of the suite tab. ERROR messages from the reader thread trigger `_handle_suite_error_disconnect()` which disconnects and stops the runner.
- `cleanup()` on each `TestSuitePanel` disconnects both `_suite_handler` and `_trigger_handler`, and calls `_runner.stop()`.

### Config persistence
- `config_1.json` stores Suite 1 state; `config_2.json` stores Suite 2 state. Both share the same `DEFAULTS` schema.
- Legacy `config.json` is auto-migrated to `config_1.json` on first launch.
- Config files are in `.gitignore` — they are machine-specific.
- Config is saved on every successful connect (suite or trigger), when the log folder changes, and on clean shutdown. New keys added to `DEFAULTS` in `config.py` are automatically merged, so old config files remain valid.
- `log_dir` key: empty string means use the default (`~/serial_logs`). `AppConfig.effective_log_dir()` resolves this. Each suite has its own `log_dir` (set via the Log folder row in the Device Connection section).
- Suite-specific connection keys: `suite_port`, `suite_baud`, `suite_parity`, `suite_line_ending`.
- `trigger_port` / `trigger_baud`: last-used trigger device port and baud rate (saved when trigger connects).
- `suite_2_visible`: persisted in `config_1.json` only; controls whether the Suite 2 pane is shown.

### CSV output files
Two CSV files are written to each suite's configured log folder on each test run:

| File | Written | Format |
|------|---------|--------|
| `test_run_<timestamp>.csv` | Created at run start, one wide-format row appended per loop iteration | Columns: `Run_Start`, `Run_End`, then `<name>_Status` + `<name>_Actual` for every test in the suite |
| `test_suite_log.csv` | One row appended per run completion | Columns: `Timestamp`, then one column per test name (value = status or blank if not in this run) |

In loop mode the per-run CSV accumulates one row per iteration; a new file is only created when a fresh run starts (i.e. after a non-looping run ends or Stop is pressed).

## GUI layout

```
ConnectionPanel   (always visible above notebook — Terminal tab connection only)
  Row 0: Port / Refresh / Baud
  Row 1: Parity / Data bits / Stop bits / Line ending      [Connect]
  Row 2: Log folder entry                                  [Browse…]
ttk.Notebook
├── Tab 1 "Terminal"
│   ├── TerminalPanel   (dark ScrolledText, expands)
│   └── CommandPanel    (entry + send + history + [ESC] [TAB] [^C] special-char buttons)
└── Tab 2 "Test Suite"
    ├── [＋ Add Suite 2] toggle button
    └── ttk.PanedWindow (horizontal, holds Suite 1 and optionally Suite 2)
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
StatusBar             (connection info + current log file path)
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

## Conventions

- All inter-thread communication goes through `queue.Queue` — no shared mutable state.
- GUI panels communicate with `MainWindow` via plain callback attributes (`on_connect`, `on_send`, etc.) set by `MainWindow._wire_callbacks()`. The `ConnectionPanel` and `CommandPanel` have no direct import of `SerialHandler`.
- `TestSuitePanel` owns its `SerialHandler` directly (`self._suite_handler`). There is no `handler_provider` lambda — the suite panel creates, connects, and disconnects its own handler.
- `_result_map: dict[test_id → (label, status)]` in `TestSuitePanel` persists results across tree repopulations (e.g. after reorder), and is cleared by "Clear Results" or at the start of each new run.
- `_current_csv_path` in `TestSuitePanel` tracks the active per-run CSV across loop iterations; it is set to `None` when a non-looping run finishes or Stop is pressed, causing the next run to open a fresh file.
- **Loop interval**: when "↻ Loop" is active and the interval spinbox is > 0, `_on_done` calls `_start_loop_countdown(seconds)` instead of restarting immediately. `_tick_loop_countdown` reschedules itself every 1 s via `self.after(1000, …)`, stores the `after()` ID in `_loop_after_id`, and updates the summary bar with "next run in Xs". When the countdown reaches 0 it calls `_start_run`. Clicking Stop during a countdown cancels the pending `after()` call and re-enables the run buttons immediately.
- The Treeview nav column shows `M` when `manual=True`, `⚙` when setup/teardown/trigger commands are present, and `M⚙` when both apply.
- `CommandPanel` special-char buttons (ESC / TAB / ^C) send a single control character with **no** line ending appended, using `on_send(char, b"")`.
