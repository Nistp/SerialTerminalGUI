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
    ├── logger.py                  # Session file logging to ~/serial_logs/
    ├── test_runner.py             # TestCase / TestResult dataclasses + TestRunner thread
    └── gui/
        ├── main_window.py         # Integration hub — owns handler, logger, poll loop
        ├── connection_panel.py    # Port / baud / parity / line-ending controls
        ├── terminal_panel.py      # Dark scrolled terminal with colour-coded TX/RX
        ├── command_panel.py       # Command entry + Up/Down history
        └── test_suite_panel.py   # Test CRUD, treeview with live result column, runner
```

## Architecture — key decisions

### Threading model
- `SerialHandler` runs one daemon reader thread (`_read_loop`) that reads bytes from the port and splits on `\n`.
- The reader thread **only** calls `queue.put()` — it never touches any Tkinter object.
- `MainWindow._poll_queue()` is rescheduled every 50 ms via `root.after()` and drains the queue, calling `terminal_panel.batch_append()` and `logger.write()` for each message.
- The `after()` poll loop is **never cancelled** — it runs even when disconnected (queue is just empty).

### TX echo
TX commands are **not** read back from the serial port. Instead `_on_send_request` immediately puts a `TerminalMessage(Direction.TX, text)` into `rx_queue` before calling `handler.send()`. This gives instant feedback and avoids half-duplex echo issues.

### Automated test runner
- `TestRunner` runs in its own daemon thread and communicates results back via `root.after(0, callback)` — never calls widget methods directly.
- **Capture mode**: before sending a test command `handler.start_capture()` creates a secondary `_capture_queue`. The reader thread writes every incoming message to both `rx_queue` (terminal) and `_capture_queue` (test runner). After the test `handler.stop_capture()` sets `_capture_queue = None`.
- **Silent navigation commands** (`setup_commands` / `teardown_commands` on `TestCase`): sent via `_execute_silent()` which uses capture mode but **never puts anything into `rx_queue`**. This means menu-navigation steps are invisible in the terminal and absent from the session log.

### Config persistence
- `config.json` in the project root stores last-used serial settings and the full test suite definition (serialised `TestCase` dicts).
- `config.json` is in `.gitignore` — it is machine-specific.
- Config is saved on every successful connect and on clean shutdown. New keys added to `DEFAULTS` in `config.py` are automatically merged, so old config files remain valid.

## GUI layout

```
ConnectionPanel   (always visible above notebook)
ttk.Notebook
├── Tab 1 "Terminal"
│   ├── TerminalPanel   (dark ScrolledText, expands)
│   └── CommandPanel    (entry + send + history)
└── Tab 2 "Test Suite"
    ├── Toolbar         (Add / Edit / Delete / Up / Down)
    ├── Treeview        (Result | ✓ | ⚙ | Name | Command | Expected | Terminator | Timeout)
    ├── Run bar         (Run Selected / Run All / Stop / delay spinbox)
    ├── Results panel   (ScrolledText with coloured background boxes per result)
    └── Summary bar
StatusBar             (connection info + current log file path)
```

## Terminal colour scheme

| Direction | Colour    |
|-----------|-----------|
| TX        | `#00BFFF` (sky blue) |
| RX        | `#00FF7F` (spring green) |
| INFO      | `#FFD700` (gold) |
| ERROR     | `#FF4444` (red) |

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
| `expected`         | —       | Substring that must appear in response (contains check) |
| `terminator`       | `"OK"`  | Line that signals end of response |
| `timeout_ms`       | `2000`  | Timeout waiting for terminator |
| `setup_commands`   | `[]`    | Navigation commands sent **silently** before the test |
| `teardown_commands`| `[]`    | Navigation commands sent **silently** after the test |
| `nav_timeout_ms`   | `1000`  | Per-step timeout for each silent navigation command |
| `enabled`          | `True`  | Included in "Run All" when checked |
| `id`               | uuid4   | Stable identifier used as Treeview iid |

## Conventions

- All inter-thread communication goes through `queue.Queue` — no shared mutable state.
- GUI panels communicate with `MainWindow` via plain callback attributes (`on_connect`, `on_send`, etc.) set by `MainWindow._wire_callbacks()`. Panels have no direct import of `SerialHandler`.
- `test_suite_panel.py` is the only panel that receives a `handler_provider` lambda (not the handler directly) so it can check `is_connected` at run time without holding a stale reference.
- `_result_map: dict[test_id → (label, status)]` in `TestSuitePanel` persists results across tree repopulations (e.g. after reorder), and is cleared by "Clear Results" or at the start of each new run.
