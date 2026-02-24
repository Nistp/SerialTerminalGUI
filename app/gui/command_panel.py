import collections
import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional


class CommandPanel(ttk.Frame):
    def __init__(self, parent, config, **kwargs):
        super().__init__(parent, **kwargs)
        self._config = config
        self._history: collections.deque = collections.deque(
            maxlen=config.get("history_size", 100)
        )
        self._history_idx: int = -1
        self._pending_input: str = ""

        self.on_send: Optional[Callable[[str, bytes], None]] = None
        self._line_ending_provider: Optional[Callable[[], bytes]] = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        self.columnconfigure(1, weight=1)

        ttk.Label(self, text="Command:").grid(row=0, column=0, padx=(4, 2), pady=4, sticky="w")

        self._entry_var = tk.StringVar()
        self._entry = ttk.Entry(self, textvariable=self._entry_var)
        self._entry.grid(row=0, column=1, padx=2, pady=4, sticky="ew")
        self._entry.bind("<Return>", lambda _: self._send_command())
        self._entry.bind("<Up>", lambda _: self._history_prev())
        self._entry.bind("<Down>", lambda _: self._history_next())
        self._entry.bind("<Escape>", lambda _: self._entry_var.set(""))
        self._entry.bind("<Control-a>", lambda _: self._entry.selection_range(0, "end"))

        self._send_btn = ttk.Button(self, text="Send", command=self._send_command, width=8)
        self._send_btn.grid(row=0, column=2, padx=(2, 4), pady=4)

        ttk.Separator(self, orient="vertical").grid(row=0, column=3, sticky="ns", padx=4)

        _special = [("ESC", "\x1b"), ("TAB", "\t"), ("^C", "\x03")]
        self._special_btns = []
        for col, (label, char) in enumerate(_special, start=4):
            btn = ttk.Button(self, text=label, width=4,
                             command=lambda c=char: self._send_special(c))
            btn.grid(row=0, column=col, padx=2, pady=4)
            self._special_btns.append(btn)

        self.set_enabled(False)

    def set_line_ending_provider(self, provider: Callable[[], bytes]) -> None:
        self._line_ending_provider = provider

    def _send_special(self, char: str) -> None:
        if self.on_send and self._line_ending_provider:
            self.on_send(char, b"")

    def _send_command(self) -> None:
        text = self._entry_var.get()
        if not text:
            return
        if not self._history or self._history[-1] != text:
            self._history.append(text)
        self._history_idx = -1
        self._pending_input = ""
        self._entry_var.set("")

        if self.on_send and self._line_ending_provider:
            self.on_send(text, self._line_ending_provider())

    def _history_prev(self) -> None:
        if not self._history:
            return
        if self._history_idx == -1:
            self._pending_input = self._entry_var.get()
            self._history_idx = len(self._history) - 1
        elif self._history_idx > 0:
            self._history_idx -= 1
        self._entry_var.set(self._history[self._history_idx])
        self._entry.icursor("end")

    def _history_next(self) -> None:
        if self._history_idx == -1:
            return
        self._history_idx += 1
        if self._history_idx >= len(self._history):
            self._history_idx = -1
            self._entry_var.set(self._pending_input)
        else:
            self._entry_var.set(self._history[self._history_idx])
        self._entry.icursor("end")

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._entry.config(state=state)
        self._send_btn.config(state=state)
        for btn in self._special_btns:
            btn.config(state=state)
        if enabled:
            self._entry.focus_set()
