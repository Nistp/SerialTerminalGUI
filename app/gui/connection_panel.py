import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

from app.config import BAUD_RATES, LINE_ENDINGS, PARITIES, STOPBITS, AppConfig
from app.serial_handler import list_serial_ports


class ConnectionPanel(ttk.LabelFrame):
    def __init__(self, parent, config: AppConfig, **kwargs):
        super().__init__(parent, text="Connection", **kwargs)
        self._config = config

        self.on_connect: Optional[Callable[[dict], None]] = None
        self.on_disconnect: Optional[Callable[[], None]] = None

        self._port_var = tk.StringVar()
        self._baud_var = tk.StringVar(value=str(config.get("baud", 115200)))
        self._parity_var = tk.StringVar()
        self._databits_var = tk.StringVar(value=str(config.get("databits", 8)))
        self._stopbits_var = tk.StringVar()
        self._line_ending_var = tk.StringVar(value=config.get("line_ending", "CRLF"))

        self._connected = False
        self._port_map: dict = {}  # display string → device name

        self._setup_ui()
        self._restore_from_config()
        self._refresh_ports()

    def _setup_ui(self) -> None:
        pad = {"padx": 4, "pady": 2}

        # Row 0: Port + Baud
        ttk.Label(self, text="Port:").grid(row=0, column=0, sticky="e", **pad)
        self._port_cb = ttk.Combobox(self, textvariable=self._port_var, width=24)
        self._port_cb.grid(row=0, column=1, sticky="ew", **pad)

        self._refresh_btn = ttk.Button(self, text="⟳", width=3, command=self._refresh_ports)
        self._refresh_btn.grid(row=0, column=2, sticky="w", **pad)

        ttk.Label(self, text="Baud:").grid(row=0, column=3, sticky="e", **pad)
        self._baud_cb = ttk.Combobox(
            self,
            textvariable=self._baud_var,
            values=[str(b) for b in BAUD_RATES],
            state="readonly",
            width=10,
        )
        self._baud_cb.grid(row=0, column=4, sticky="ew", **pad)

        # Row 1: Parity + Data bits + Stop bits + Line ending
        ttk.Label(self, text="Parity:").grid(row=1, column=0, sticky="e", **pad)
        self._parity_cb = ttk.Combobox(
            self,
            textvariable=self._parity_var,
            values=list(PARITIES.keys()),
            state="readonly",
            width=8,
        )
        self._parity_cb.grid(row=1, column=1, sticky="w", **pad)

        ttk.Label(self, text="Data bits:").grid(row=1, column=3, sticky="e", **pad)
        self._databits_cb = ttk.Combobox(
            self,
            textvariable=self._databits_var,
            values=["5", "6", "7", "8"],
            state="readonly",
            width=4,
        )
        self._databits_cb.grid(row=1, column=4, sticky="w", **pad)

        ttk.Label(self, text="Stop bits:").grid(row=1, column=5, sticky="e", **pad)
        self._stopbits_cb = ttk.Combobox(
            self,
            textvariable=self._stopbits_var,
            values=list(STOPBITS.keys()),
            state="readonly",
            width=4,
        )
        self._stopbits_cb.grid(row=1, column=6, sticky="w", **pad)

        ttk.Label(self, text="Line ending:").grid(row=1, column=7, sticky="e", **pad)
        self._le_cb = ttk.Combobox(
            self,
            textvariable=self._line_ending_var,
            values=list(LINE_ENDINGS.keys()),
            state="readonly",
            width=6,
        )
        self._le_cb.grid(row=1, column=8, sticky="w", **pad)

        # Connect button (far right, spanning both rows)
        self._connect_btn = ttk.Button(
            self, text="Connect", command=self._on_connect_click, width=12
        )
        self._connect_btn.grid(row=0, column=9, rowspan=2, padx=8, pady=4, sticky="ns")

    def _restore_from_config(self) -> None:
        from app.config import PARITIES_INV, STOPBITS_INV

        saved_parity = self._config.get("parity", "N")
        self._parity_var.set(PARITIES_INV.get(saved_parity, "None"))

        saved_stopbits = self._config.get("stopbits", 1)
        self._stopbits_var.set(STOPBITS_INV.get(saved_stopbits, "1"))

    def _refresh_ports(self) -> None:
        ports = list_serial_ports()
        self._port_map = {}
        if ports:
            displays = []
            for dev, desc in ports:
                display = f"{dev} — {desc}" if desc != dev else dev
                self._port_map[display] = dev
                displays.append(display)
            self._port_cb["values"] = displays

            saved = self._config.get("port", "")
            match = next((d for d, v in self._port_map.items() if v == saved), None)
            if match:
                self._port_var.set(match)
            else:
                self._port_var.set(displays[0])
            self._connect_btn.config(state="normal")
        else:
            self._port_cb["values"] = ["(no ports found)"]
            self._port_var.set("(no ports found)")
            self._connect_btn.config(state="disabled")

    def _on_connect_click(self) -> None:
        if self._connected:
            if self.on_disconnect:
                self.on_disconnect()
        else:
            if self.on_connect:
                self.on_connect(self.get_params())

    def get_params(self) -> dict:
        display = self._port_var.get()
        port = self._port_map.get(display, display.split(" — ")[0].strip())
        return {
            "port": port,
            "baud": int(self._baud_var.get()),
            "parity": PARITIES.get(self._parity_var.get(), "N"),
            "databits": int(self._databits_var.get()),
            "stopbits": STOPBITS.get(self._stopbits_var.get(), 1),
        }

    def get_line_ending(self) -> bytes:
        return LINE_ENDINGS.get(self._line_ending_var.get(), b"\r\n")

    def get_line_ending_key(self) -> str:
        return self._line_ending_var.get()

    def set_connected(self, connected: bool) -> None:
        self._connected = connected
        state_config = "disabled" if connected else "readonly"
        state_entry = "disabled" if connected else "normal"
        for widget in (self._baud_cb, self._parity_cb, self._databits_cb,
                       self._stopbits_cb, self._le_cb):
            widget.config(state=state_config)
        self._port_cb.config(state=state_entry)
        self._refresh_btn.config(state="disabled" if connected else "normal")
        self._connect_btn.config(text="Disconnect" if connected else "Connect")
