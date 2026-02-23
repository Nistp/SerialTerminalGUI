import tkinter as tk
from tkinter import filedialog, scrolledtext, ttk
from typing import List

from app.serial_handler import Direction, TerminalMessage

_TAG_MAP = {
    Direction.TX:    "tx",
    Direction.RX:    "rx",
    Direction.INFO:  "info",
    Direction.ERROR: "error",
}

_COLORS = {
    "tx":    "#00BFFF",
    "rx":    "#00FF7F",
    "info":  "#FFD700",
    "error": "#FF4444",
}


class TerminalPanel(ttk.Frame):
    def __init__(self, parent, config, **kwargs):
        super().__init__(parent, **kwargs)
        self._config = config
        self._max_lines: int = config.get("max_lines", 5000)
        self._setup_ui()

    def _setup_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)

        font_size = self._config.get("font_size", 10)
        self._text = scrolledtext.ScrolledText(
            self,
            state="disabled",
            font=("Courier", font_size),
            bg="#1C1C1C",
            fg="#E0E0E0",
            insertbackground="#E0E0E0",
            wrap="word",
            relief="flat",
        )
        self._text.grid(row=0, column=0, sticky="nsew")

        for tag, color in _COLORS.items():
            self._text.tag_configure(tag, foreground=color)

        toolbar = ttk.Frame(self)
        toolbar.grid(row=1, column=0, sticky="ew", pady=(2, 0))

        self._autoscroll_var = tk.BooleanVar(value=self._config.get("autoscroll", True))
        ttk.Checkbutton(
            toolbar, text="Autoscroll", variable=self._autoscroll_var
        ).pack(side="left", padx=4)

        self._show_ts_var = tk.BooleanVar(value=self._config.get("show_timestamp", True))
        ttk.Checkbutton(
            toolbar, text="Timestamps", variable=self._show_ts_var
        ).pack(side="left", padx=4)

        ttk.Button(toolbar, text="Clear", command=self.clear).pack(side="left", padx=4)
        ttk.Button(toolbar, text="Save As…", command=self.save_to_file).pack(side="left", padx=4)

    def _format_line(self, msg: TerminalMessage) -> str:
        if self._show_ts_var.get():
            ts = msg.timestamp.strftime("%H:%M:%S.%f")[:-3]
            return f"[{ts}] [{msg.direction.value:<5s}] {msg.text}\n"
        return f"[{msg.direction.value:<5s}] {msg.text}\n"

    def batch_append(self, messages: List[TerminalMessage]) -> None:
        self._text.config(state="normal")
        for msg in messages:
            tag = _TAG_MAP.get(msg.direction, "rx")
            self._text.insert("end", self._format_line(msg), tag)
        self._trim_lines()
        self._text.config(state="disabled")
        if self._autoscroll_var.get():
            self._text.see("end")

    def _trim_lines(self) -> None:
        line_count = int(self._text.index("end-1c").split(".")[0])
        if line_count > self._max_lines:
            excess = line_count - self._max_lines
            self._text.delete("1.0", f"{excess + 1}.0")

    def clear(self) -> None:
        self._text.config(state="normal")
        self._text.delete("1.0", "end")
        self._text.config(state="disabled")

    def save_to_file(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text files", "*.txt"), ("Log files", "*.log"), ("All files", "*.*")],
            title="Save terminal output",
        )
        if not path:
            return
        content = self._text.get("1.0", "end")
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(content)
        except OSError as exc:
            from tkinter import messagebox
            messagebox.showerror("Save Failed", str(exc))
