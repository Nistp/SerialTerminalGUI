import queue
import tkinter as tk
from tkinter import messagebox, ttk

from app.config import AppConfig
from app.logger import SessionLogger
from app.serial_handler import Direction, SerialHandler, TerminalMessage
from app.gui.connection_panel import ConnectionPanel
from app.gui.terminal_panel import TerminalPanel
from app.gui.command_panel import CommandPanel
from app.gui.test_suite_panel import TestSuitePanel

_POLL_MAX = 200  # max messages drained per poll tick


class MainWindow:
    def __init__(self, root: tk.Tk, config: AppConfig) -> None:
        self.root = root
        self._config = config
        self._handler = SerialHandler()
        self._logger = SessionLogger()

        self._setup_window()
        self._create_widgets()
        self._wire_callbacks()
        self._start_poll()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ------------------------------------------------------------------ #
    #  Window setup
    # ------------------------------------------------------------------ #

    def _setup_window(self) -> None:
        self.root.title("Serial Terminal")
        self.root.minsize(900, 620)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

    def _create_widgets(self) -> None:
        # Connection panel (always visible, above notebook)
        self._conn_panel = ConnectionPanel(self.root, self._config)
        self._conn_panel.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 0))

        # Notebook: Terminal | Test Suite
        self._notebook = ttk.Notebook(self.root)
        self._notebook.grid(row=1, column=0, sticky="nsew", padx=6, pady=4)

        # Tab 1: Terminal
        tab1 = ttk.Frame(self._notebook)
        tab1.columnconfigure(0, weight=1)
        tab1.rowconfigure(0, weight=1)
        self._notebook.add(tab1, text="  Terminal  ")

        self._terminal = TerminalPanel(tab1, self._config)
        self._terminal.grid(row=0, column=0, sticky="nsew")

        self._cmd_panel = CommandPanel(tab1, self._config)
        self._cmd_panel.grid(row=1, column=0, sticky="ew", padx=2, pady=(0, 2))

        # Tab 2: Test Suite
        tab2 = ttk.Frame(self._notebook)
        tab2.columnconfigure(0, weight=1)
        tab2.rowconfigure(0, weight=1)
        self._notebook.add(tab2, text="  Test Suite  ")

        self._test_panel = TestSuitePanel(
            tab2,
            config=self._config,
            handler_provider=lambda: self._handler,
            le_provider=self._conn_panel.get_line_ending,
        )
        self._test_panel.grid(row=0, column=0, sticky="nsew", padx=2, pady=2)

        # Status bar
        self._status_frame = ttk.Frame(self.root)
        self._status_frame.grid(row=2, column=0, sticky="ew", padx=6, pady=(0, 4))

        self._status_var = tk.StringVar(value="Disconnected")
        ttk.Label(
            self._status_frame,
            textvariable=self._status_var,
            relief="sunken",
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        self._log_var = tk.StringVar(value="")
        ttk.Label(
            self._status_frame,
            textvariable=self._log_var,
            relief="sunken",
            anchor="w",
        ).pack(side="left", fill="x", expand=True)

    def _wire_callbacks(self) -> None:
        self._conn_panel.on_connect    = self._on_connect_request
        self._conn_panel.on_disconnect = self._on_disconnect_request
        self._cmd_panel.on_send        = self._on_send_request
        self._cmd_panel.set_line_ending_provider(self._conn_panel.get_line_ending)

    # ------------------------------------------------------------------ #
    #  Queue polling
    # ------------------------------------------------------------------ #

    def _start_poll(self) -> None:
        interval = self._config.get("poll_interval_ms", 50)
        self.root.after(interval, self._poll_queue)

    def _poll_queue(self) -> None:
        messages = []
        try:
            for _ in range(_POLL_MAX):
                messages.append(self._handler.rx_queue.get_nowait())
        except queue.Empty:
            pass

        if messages:
            self._terminal.batch_append(messages)
            for msg in messages:
                self._logger.write(msg)
            for msg in messages:
                if msg.direction == Direction.ERROR:
                    self._handle_error_disconnect()
                    break

        interval = self._config.get("poll_interval_ms", 50)
        self.root.after(interval, self._poll_queue)

    # ------------------------------------------------------------------ #
    #  Connect / disconnect
    # ------------------------------------------------------------------ #

    def _on_connect_request(self, params: dict) -> None:
        try:
            self._handler.connect(**params)
        except Exception as exc:
            messagebox.showerror("Connection Failed", str(exc))
            return

        log_dir = self._config.effective_log_dir()
        try:
            log_path = self._logger.open_session(log_dir)
            self._log_var.set(f"Log: {log_path}")
        except OSError as exc:
            self._log_var.set(f"Log: failed ({exc})")

        desc = (
            f"{params['port']}  {params['baud']},{params['databits']}"
            f"{params['parity']}{params['stopbits']}"
        )
        self._handler.rx_queue.put(
            TerminalMessage(Direction.INFO, f"Connected — {desc}")
        )
        self._status_var.set(f"Connected: {desc}")
        self._update_ui_state(connected=True)
        self._save_connection_settings(params)

    def _on_disconnect_request(self) -> None:
        self._handler.rx_queue.put(
            TerminalMessage(Direction.INFO, "Disconnected")
        )
        self._handler.disconnect()
        self._logger.close_session()
        self._status_var.set("Disconnected")
        self._log_var.set("")
        self._update_ui_state(connected=False)

    def _handle_error_disconnect(self) -> None:
        if not self._handler.is_connected:
            return
        self._handler.disconnect()
        self._logger.close_session()
        self._status_var.set("Disconnected (error)")
        self._log_var.set("")
        self._update_ui_state(connected=False)

    def _update_ui_state(self, connected: bool) -> None:
        self._conn_panel.set_connected(connected)
        self._cmd_panel.set_enabled(connected)
        self._test_panel.set_enabled(connected)

    def _save_connection_settings(self, params: dict) -> None:
        self._config["port"]        = params["port"]
        self._config["baud"]        = params["baud"]
        self._config["parity"]      = params["parity"]
        self._config["databits"]    = params["databits"]
        self._config["stopbits"]    = params["stopbits"]
        self._config["line_ending"] = self._conn_panel.get_line_ending_key()
        self._config.save()

    # ------------------------------------------------------------------ #
    #  Send
    # ------------------------------------------------------------------ #

    def _on_send_request(self, text: str, line_ending: bytes) -> None:
        if not self._handler.is_connected:
            return
        try:
            self._handler.send(text, line_ending)
            self._handler.rx_queue.put(TerminalMessage(Direction.TX, text))
        except Exception as exc:
            self._handler.rx_queue.put(
                TerminalMessage(Direction.ERROR, f"Send failed: {exc}")
            )

    # ------------------------------------------------------------------ #
    #  Shutdown
    # ------------------------------------------------------------------ #

    def _on_closing(self) -> None:
        if self._handler.is_connected:
            self._handler.disconnect()
        self._logger.close_session()
        self._config.save()
        self.root.destroy()
