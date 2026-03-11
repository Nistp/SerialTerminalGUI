import pathlib
import queue
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Optional

from app.config import AppConfig, _TERMINAL_KEYS
from app.logger import SessionLogger
from app.serial_handler import Direction, SerialHandler, TerminalMessage
from app.gui.connection_panel import ConnectionPanel
from app.gui.terminal_panel import TerminalPanel
from app.gui.command_panel import CommandPanel

_POLL_MAX = 200


class TerminalConfigProxy:
    """Thin adapter that makes AppConfig look like a single-terminal config dict.

    ConnectionPanel, TerminalPanel, and CommandPanel all call config.get() /
    config[key] / config.save() / config.effective_log_dir().  This proxy
    routes terminal-specific keys (port, baud, parity …) to the correct
    terminals[index] slice and falls back to the shared AppConfig for all
    display/behaviour keys (autoscroll, font_size, max_lines …).
    """

    def __init__(self, app_config: AppConfig, index: int) -> None:
        self._cfg = app_config
        self._idx = index

    def get(self, key, default=None):
        if key in _TERMINAL_KEYS:
            return self._cfg.get_terminal_config(self._idx).get(key, default)
        return self._cfg.get(key, default)

    def __getitem__(self, key):
        if key in _TERMINAL_KEYS:
            return self._cfg.get_terminal_config(self._idx)[key]
        return self._cfg[key]

    def __setitem__(self, key, value) -> None:
        if key in _TERMINAL_KEYS:
            self._cfg.save_terminal_config(self._idx, {key: value})
        else:
            self._cfg[key] = value

    def save(self) -> None:
        self._cfg.save()

    def effective_log_dir(self) -> pathlib.Path:
        return self._cfg.effective_log_dir_for(self._cfg.get_terminal_config(self._idx))


class TerminalPane(ttk.Frame):
    """Self-contained terminal: ConnectionPanel + TerminalPanel + CommandPanel
    with its own SerialHandler, SessionLogger, and poll loop.

    Multiple instances can run simultaneously on different serial ports.
    """

    def __init__(
        self,
        parent,
        config: AppConfig,
        terminal_index: int,
        **kwargs,
    ) -> None:
        super().__init__(parent, **kwargs)
        self._config = config
        self._index = terminal_index
        self._proxy = TerminalConfigProxy(config, terminal_index)

        self._handler = SerialHandler()
        self._logger = SessionLogger()

        self._setup_ui()
        self._wire_callbacks()
        self._start_poll()

    # ------------------------------------------------------------------ #
    #  UI construction
    # ------------------------------------------------------------------ #

    def _setup_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        self._conn_panel = ConnectionPanel(self, self._proxy)
        self._conn_panel.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))

        self._terminal = TerminalPanel(self, self._proxy)
        self._terminal.grid(row=1, column=0, sticky="nsew")

        self._cmd_panel = CommandPanel(self, self._proxy)
        self._cmd_panel.grid(row=2, column=0, sticky="ew", padx=2, pady=(0, 2))

        status_frame = ttk.Frame(self)
        status_frame.grid(row=3, column=0, sticky="ew", padx=4, pady=(0, 2))

        self._status_var = tk.StringVar(value="Disconnected")
        ttk.Label(
            status_frame,
            textvariable=self._status_var,
            relief="sunken",
            anchor="w",
        ).pack(side="left", fill="x", expand=True, padx=(0, 4))

        self._log_var = tk.StringVar(value="")
        ttk.Label(
            status_frame,
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
    #  Poll loop  (runs forever via self.after — stops when widget destroyed)
    # ------------------------------------------------------------------ #

    def _start_poll(self) -> None:
        interval = self._config.get("poll_interval_ms", 50)
        self.after(interval, self._poll_queue)

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
        self.after(interval, self._poll_queue)

    # ------------------------------------------------------------------ #
    #  Connect / disconnect
    # ------------------------------------------------------------------ #

    def _on_connect_request(self, params: dict) -> None:
        try:
            self._handler.connect(**params)
        except Exception as exc:
            messagebox.showerror("Connection Failed", str(exc))
            return

        log_dir = self._proxy.effective_log_dir()
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

    def _save_connection_settings(self, params: dict) -> None:
        self._config.save_terminal_config(self._index, {
            "port":        params["port"],
            "baud":        params["baud"],
            "parity":      params["parity"],
            "databits":    params["databits"],
            "stopbits":    params["stopbits"],
            "line_ending": self._conn_panel.get_line_ending_key(),
        })
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
    #  Cleanup
    # ------------------------------------------------------------------ #

    def cleanup(self) -> None:
        """Disconnect and close logger. Call before destroying the widget."""
        if self._handler.is_connected:
            self._handler.disconnect()
        self._logger.close_session()
