import csv
import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Callable, List, Optional

from app.config import AppConfig
from app.serial_handler import SerialHandler
from app.test_runner import TestCase, TestResult, TestRunner

# background / foreground for each result box
_RESULT_TAGS = {
    "PASS":    {"background": "#0D3B1F", "foreground": "#00FF7F"},
    "FAIL":    {"background": "#3B0D0D", "foreground": "#FF5555"},
    "TIMEOUT": {"background": "#3B2D00", "foreground": "#FFD700"},
    "ERROR":   {"background": "#3B1A00", "foreground": "#FF9100"},
}

_CHECKBOX_CHECKED = "☑"
_CHECKBOX_EMPTY   = "☐"

_COLUMNS = ("enabled", "nav", "name", "command", "expected", "terminator", "timeout_ms", "result")
_HEADINGS = {
    "result":      "Result",
    "enabled":     "✓",
    "nav":         "⚙",   # indicates setup/teardown navigation steps present
    "name":        "Name",
    "command":     "Command",
    "expected":    "Expected (contains)",
    "terminator":  "Terminator",
    "timeout_ms":  "Timeout (ms)",
}
_WIDTHS = {
    "result":     80,
    "enabled":    30,
    "nav":        24,
    "name":       140,
    "command":    140,
    "expected":   160,
    "terminator": 80,
    "timeout_ms": 80,
}

# Treeview row tags for each result state
_ROW_TAGS = {
    "PASS":    {"foreground": "#00FF7F"},
    "FAIL":    {"foreground": "#FF5555"},
    "TIMEOUT": {"foreground": "#FFD700"},
    "ERROR":   {"foreground": "#FF9100"},
}
_RESULT_LABEL = {
    "PASS":    "✔  PASS",
    "FAIL":    "✘  FAIL",
    "TIMEOUT": "⏱  TIMEOUT",
    "ERROR":   "⚠  ERROR",
}


class TestSuitePanel(ttk.Frame):
    def __init__(self, parent, config: AppConfig,
                 handler_provider: Callable[[], SerialHandler],
                 le_provider: Callable[[], bytes],
                 **kwargs):
        super().__init__(parent, **kwargs)
        self._config = config
        self._handler_provider = handler_provider
        self._le_provider = le_provider
        self._tests: List[TestCase] = []
        self._runner = TestRunner()
        self._pass_count = 0
        self._fail_count = 0
        self._total_count = 0
        # Maps test ID → result label string; persists across tree repopulations
        self._result_map: dict = {}
        # Accumulated results for the current (or most recent) run
        self._run_results: List[TestResult] = []
        self._run_timestamps: List[datetime.datetime] = []
        # Loop mode state
        self._loop_var = tk.BooleanVar(value=False)
        self._current_run_tests: List[TestCase] = []
        self._stop_requested: bool = False

        self._setup_ui()
        self._load_tests_from_config()

    def _setup_ui(self) -> None:
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=2)
        self.rowconfigure(3, weight=1)

        # --- Toolbar ---
        toolbar = ttk.Frame(self)
        toolbar.grid(row=0, column=0, sticky="ew", padx=4, pady=(4, 0))

        ttk.Button(toolbar, text="+ Add",   command=self._add_test).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Edit",    command=self._edit_test).pack(side="left", padx=2)
        ttk.Button(toolbar, text="Delete",  command=self._delete_test).pack(side="left", padx=2)
        ttk.Button(toolbar, text="↑ Up",   command=self._move_up).pack(side="left", padx=2)
        ttk.Button(toolbar, text="↓ Down", command=self._move_down).pack(side="left", padx=2)

        # --- Treeview ---
        tree_frame = ttk.Frame(self)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=4, pady=4)
        tree_frame.columnconfigure(0, weight=1)
        tree_frame.rowconfigure(0, weight=1)

        self._tree = ttk.Treeview(
            tree_frame,
            columns=_COLUMNS,
            show="headings",
            selectmode="browse",
        )
        for col in _COLUMNS:
            self._tree.heading(col, text=_HEADINGS[col])
            self._tree.column(col, width=_WIDTHS[col], minwidth=30, stretch=(col == "name"))

        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        for tag_name, colors in _ROW_TAGS.items():
            self._tree.tag_configure(tag_name, **colors)

        self._tree.bind("<Double-1>", lambda _: self._edit_test())
        self._tree.bind("<Button-1>", self._on_tree_click)

        # --- Run bar ---
        run_bar = ttk.Frame(self)
        run_bar.grid(row=2, column=0, sticky="ew", padx=4, pady=2)

        self._run_sel_btn = ttk.Button(
            run_bar, text="▶ Run Selected", command=self._run_selected
        )
        self._run_sel_btn.pack(side="left", padx=2)

        self._run_all_btn = ttk.Button(
            run_bar, text="▶▶ Run All", command=self._run_all
        )
        self._run_all_btn.pack(side="left", padx=2)

        self._stop_btn = ttk.Button(
            run_bar, text="■ Stop", command=self._stop_run, state="disabled"
        )
        self._stop_btn.pack(side="left", padx=2)

        ttk.Separator(run_bar, orient="vertical").pack(side="left", padx=8, fill="y")
        ttk.Checkbutton(run_bar, text="↻ Loop", variable=self._loop_var).pack(side="left", padx=2)

        ttk.Separator(run_bar, orient="vertical").pack(side="left", padx=8, fill="y")
        ttk.Label(run_bar, text="Delay between tests (ms):").pack(side="left")
        self._delay_var = tk.StringVar(value=str(self._config.get("test_delay_ms", 200)))
        ttk.Spinbox(run_bar, from_=0, to=10000, increment=50,
                    textvariable=self._delay_var, width=6).pack(side="left", padx=4)

        # --- Results panel ---
        self._results = scrolledtext.ScrolledText(
            self,
            state="disabled",
            font=("Courier", 9),
            bg="#1C1C1C",
            fg="#E0E0E0",
            height=8,
            relief="flat",
        )
        self._results.grid(row=3, column=0, sticky="nsew", padx=4, pady=(0, 2))
        for status, colors in _RESULT_TAGS.items():
            self._results.tag_configure(status, **colors, font=("Courier", 9, "bold"))
        self._results.tag_configure("header", foreground="#AAAAAA")

        # --- Summary bar ---
        summary_bar = ttk.Frame(self)
        summary_bar.grid(row=4, column=0, sticky="ew", padx=4, pady=(0, 4))

        self._summary_var = tk.StringVar(value="No results yet")
        ttk.Label(summary_bar, textvariable=self._summary_var).pack(side="left")
        ttk.Button(summary_bar, text="Clear Results", command=self._clear_results).pack(side="right")
        ttk.Button(summary_bar, text="Export CSV…", command=self._export_csv).pack(side="right", padx=4)

        self.set_enabled(False)

    # ------------------------------------------------------------------ #
    #  Treeview helpers
    # ------------------------------------------------------------------ #

    def _populate_tree(self) -> None:
        self._tree.delete(*self._tree.get_children())
        for tc in self._tests:
            has_nav = bool(tc.setup_commands or tc.teardown_commands)
            result_entry = self._result_map.get(tc.id)  # (label, status) or None
            result_label = result_entry[0] if result_entry else ""
            result_tag   = result_entry[1] if result_entry else ""
            self._tree.insert(
                "", "end", iid=tc.id,
                values=(
                    _CHECKBOX_CHECKED if tc.enabled else _CHECKBOX_EMPTY,
                    "⚙" if has_nav else "",
                    tc.name,
                    tc.command,
                    tc.expected,
                    tc.terminator,
                    tc.timeout_ms,
                    result_label,
                ),
                tags=(result_tag,) if result_tag else (),
            )

    def _selected_test(self) -> Optional[TestCase]:
        sel = self._tree.selection()
        if not sel:
            return None
        iid = sel[0]
        return next((t for t in self._tests if t.id == iid), None)

    def _selected_index(self) -> int:
        sel = self._tree.selection()
        if not sel:
            return -1
        iid = sel[0]
        return next((i for i, t in enumerate(self._tests) if t.id == iid), -1)

    def _on_tree_click(self, event) -> None:
        region = self._tree.identify_region(event.x, event.y)
        col = self._tree.identify_column(event.x)
        if region == "cell" and col == "#1":  # enabled column
            item = self._tree.identify_row(event.y)
            if item:
                tc = next((t for t in self._tests if t.id == item), None)
                if tc:
                    tc.enabled = not tc.enabled
                    self._tree.set(item, "enabled",
                                   _CHECKBOX_CHECKED if tc.enabled else _CHECKBOX_EMPTY)
                    self._save_tests_to_config()

    # ------------------------------------------------------------------ #
    #  Test CRUD
    # ------------------------------------------------------------------ #

    def _add_test(self) -> None:
        self._open_test_dialog(None)

    def _edit_test(self) -> None:
        tc = self._selected_test()
        if tc is None:
            messagebox.showinfo("Edit Test", "Select a test to edit.")
            return
        self._open_test_dialog(tc)

    def _delete_test(self) -> None:
        tc = self._selected_test()
        if tc is None:
            return
        if messagebox.askyesno("Delete Test", f"Delete '{tc.name}'?"):
            self._tests = [t for t in self._tests if t.id != tc.id]
            self._populate_tree()
            self._save_tests_to_config()

    def _move_up(self) -> None:
        idx = self._selected_index()
        if idx <= 0:
            return
        self._tests[idx], self._tests[idx - 1] = self._tests[idx - 1], self._tests[idx]
        self._populate_tree()
        self._tree.selection_set(self._tests[idx - 1].id)
        self._save_tests_to_config()

    def _move_down(self) -> None:
        idx = self._selected_index()
        if idx < 0 or idx >= len(self._tests) - 1:
            return
        self._tests[idx], self._tests[idx + 1] = self._tests[idx + 1], self._tests[idx]
        self._populate_tree()
        self._tree.selection_set(self._tests[idx + 1].id)
        self._save_tests_to_config()

    def _open_test_dialog(self, tc: Optional[TestCase]) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("Edit Test" if tc else "Add Test")
        dialog.resizable(True, True)
        dialog.grab_set()
        dialog.columnconfigure(1, weight=1)

        pad = {"padx": 8, "pady": 3}

        # --- Single-line fields ---
        single_fields = [
            ("Name:",                tc.name        if tc else "",    "name"),
            ("Command:",             tc.command     if tc else "",    "command"),
            ("Expected (contains):", tc.expected    if tc else "",    "expected"),
            ("Terminator:",          tc.terminator  if tc else "OK",  "terminator"),
            ("Timeout (ms):",        str(tc.timeout_ms)  if tc else "2000", "timeout_ms"),
            ("Nav timeout (ms):",    str(tc.nav_timeout_ms) if tc else "1000", "nav_timeout_ms"),
        ]

        vars_: dict = {}
        for row, (label, default, key) in enumerate(single_fields):
            ttk.Label(dialog, text=label).grid(row=row, column=0, sticky="e", **pad)
            v = tk.StringVar(value=default)
            vars_[key] = v
            ttk.Entry(dialog, textvariable=v, width=40).grid(
                row=row, column=1, sticky="ew", **pad
            )

        sep_row = len(single_fields)
        ttk.Separator(dialog, orient="horizontal").grid(
            row=sep_row, column=0, columnspan=2, sticky="ew", pady=6, padx=4
        )

        # --- Multiline: setup commands ---
        setup_row = sep_row + 1
        ttk.Label(
            dialog,
            text="Setup commands\n(one per line, not logged):",
            justify="right",
        ).grid(row=setup_row, column=0, sticky="ne", **pad)

        setup_frame = ttk.Frame(dialog)
        setup_frame.grid(row=setup_row, column=1, sticky="nsew", **pad)
        setup_frame.columnconfigure(0, weight=1)
        setup_frame.rowconfigure(0, weight=1)
        dialog.rowconfigure(setup_row, weight=1)

        self._setup_text = tk.Text(setup_frame, height=4, width=40, wrap="none",
                                   font=("Courier", 9))
        setup_vsb = ttk.Scrollbar(setup_frame, orient="vertical",
                                  command=self._setup_text.yview)
        self._setup_text.configure(yscrollcommand=setup_vsb.set)
        self._setup_text.grid(row=0, column=0, sticky="nsew")
        setup_vsb.grid(row=0, column=1, sticky="ns")
        if tc and tc.setup_commands:
            self._setup_text.insert("1.0", "\n".join(tc.setup_commands))

        # --- Multiline: teardown commands ---
        td_row = setup_row + 1
        ttk.Label(
            dialog,
            text="Teardown commands\n(one per line, not logged):",
            justify="right",
        ).grid(row=td_row, column=0, sticky="ne", **pad)

        td_frame = ttk.Frame(dialog)
        td_frame.grid(row=td_row, column=1, sticky="nsew", **pad)
        td_frame.columnconfigure(0, weight=1)
        td_frame.rowconfigure(0, weight=1)
        dialog.rowconfigure(td_row, weight=1)

        self._td_text = tk.Text(td_frame, height=4, width=40, wrap="none",
                                font=("Courier", 9))
        td_vsb = ttk.Scrollbar(td_frame, orient="vertical",
                               command=self._td_text.yview)
        self._td_text.configure(yscrollcommand=td_vsb.set)
        self._td_text.grid(row=0, column=0, sticky="nsew")
        td_vsb.grid(row=0, column=1, sticky="ns")
        if tc and tc.teardown_commands:
            self._td_text.insert("1.0", "\n".join(tc.teardown_commands))

        # --- OK / Cancel ---
        btn_row = td_row + 1

        def _read_cmd_lines(widget: tk.Text) -> list:
            raw = widget.get("1.0", "end-1c")
            return [ln for ln in raw.splitlines() if ln.strip()]

        def _ok():
            name = vars_["name"].get().strip()
            if not name:
                messagebox.showwarning("Validation", "Name is required.", parent=dialog)
                return
            try:
                timeout     = int(vars_["timeout_ms"].get())
                nav_timeout = int(vars_["nav_timeout_ms"].get())
            except ValueError:
                messagebox.showwarning("Validation", "Timeouts must be integers.", parent=dialog)
                return

            setup_cmds = _read_cmd_lines(self._setup_text)
            td_cmds    = _read_cmd_lines(self._td_text)

            if tc is not None:
                tc.name              = name
                tc.command           = vars_["command"].get().strip()
                tc.expected          = vars_["expected"].get().strip()
                tc.terminator        = vars_["terminator"].get().strip()
                tc.timeout_ms        = timeout
                tc.nav_timeout_ms    = nav_timeout
                tc.setup_commands    = setup_cmds
                tc.teardown_commands = td_cmds
            else:
                new_tc = TestCase(
                    name=name,
                    command=vars_["command"].get().strip(),
                    expected=vars_["expected"].get().strip(),
                    terminator=vars_["terminator"].get().strip(),
                    timeout_ms=timeout,
                    nav_timeout_ms=nav_timeout,
                    setup_commands=setup_cmds,
                    teardown_commands=td_cmds,
                )
                self._tests.append(new_tc)

            self._populate_tree()
            self._save_tests_to_config()
            dialog.destroy()

        ttk.Button(dialog, text="OK",     command=_ok).grid(
            row=btn_row, column=0, padx=8, pady=8, sticky="e"
        )
        ttk.Button(dialog, text="Cancel", command=dialog.destroy).grid(
            row=btn_row, column=1, padx=8, pady=8, sticky="w"
        )
        # Don't bind <Return> globally — it would fire inside the Text widgets
        dialog.bind("<Escape>", lambda _: dialog.destroy())

    # ------------------------------------------------------------------ #
    #  Run logic
    # ------------------------------------------------------------------ #

    def _run_selected(self) -> None:
        sel = self._tree.selection()
        if not sel:
            messagebox.showinfo("Run", "Select one or more tests first.")
            return
        tests = [t for t in self._tests if t.id in sel]
        self._start_run(tests)

    def _run_all(self) -> None:
        tests = [t for t in self._tests if t.enabled]
        if not tests:
            messagebox.showinfo("Run All", "No enabled tests.")
            return
        self._start_run(tests)

    def _start_run(self, tests: List[TestCase]) -> None:
        handler = self._handler_provider()
        if not handler.is_connected:
            messagebox.showwarning("Not Connected", "Connect to a serial port first.")
            return

        self._current_run_tests = tests
        self._stop_requested = False
        self._pass_count = 0
        self._fail_count = 0
        self._total_count = len(tests)
        self._run_results = []
        self._run_timestamps = []

        # Reset the result column for tests that are about to run
        for tc in tests:
            self._result_map.pop(tc.id, None)
            if self._tree.exists(tc.id):
                self._tree.set(tc.id, "result", "")
                self._tree.item(tc.id, tags=())

        self._append_result(
            f"── Running {len(tests)} test(s) ──", "header"
        )

        self._run_sel_btn.config(state="disabled")
        self._run_all_btn.config(state="disabled")
        self._stop_btn.config(state="normal")

        try:
            delay_ms = int(self._delay_var.get())
        except ValueError:
            delay_ms = 200

        def _safe_on_result(result: TestResult) -> None:
            self.after(0, lambda r=result: self._on_result(r))

        def _safe_on_done() -> None:
            self.after(0, self._on_done)

        self._runner.run(
            tests=tests,
            handler=handler,
            line_ending=self._le_provider(),
            on_result=_safe_on_result,
            on_done=_safe_on_done,
            delay_ms=delay_ms,
        )

    def _stop_run(self) -> None:
        self._stop_requested = True
        self._runner.stop()

    def _on_result(self, result: TestResult) -> None:
        status = result.status
        label = _RESULT_LABEL.get(status, status)

        # Update the treeview row live
        self._result_map[result.test.id] = (label, status)
        if self._tree.exists(result.test.id):
            self._tree.set(result.test.id, "result", label)
            self._tree.item(result.test.id, tags=(status,))

        # Also append to the results log panel below
        _ICON = {"PASS": "✔", "FAIL": "✘", "TIMEOUT": "⏱", "ERROR": "⚠"}
        actual_preview = result.actual.replace("\n", " | ")[:50]
        line = (
            f" {_ICON.get(status, '?')} {status:<7s}  {result.test.name}  "
            f"({result.duration_ms:.0f}ms)"
            + (f"  {actual_preview}" if actual_preview else "")
        )
        self._append_result(line, status)

        self._run_results.append(result)
        self._run_timestamps.append(datetime.datetime.now())

        if status == "PASS":
            self._pass_count += 1
        else:
            self._fail_count += 1

        done = self._pass_count + self._fail_count
        self._summary_var.set(
            f"{self._pass_count} / {done} passed"
            + (f" ({self._total_count - done} remaining)" if done < self._total_count else "")
        )

    def _on_done(self) -> None:
        completion_ts = datetime.datetime.now()
        total = self._pass_count + self._fail_count
        self._append_result(
            f"── Done: {self._pass_count}/{total} passed ──", "header"
        )
        self._summary_var.set(f"{self._pass_count} / {total} passed")

        # Append one summary row to the cumulative run log
        if self._run_results:
            try:
                log_dir = self._config.effective_log_dir()
                log_dir.mkdir(parents=True, exist_ok=True)
                csv_path = log_dir / "test_suite_log.csv"
                self._append_run_row(csv_path, completion_ts)
                self._append_result(f"  CSV log → {csv_path}", "header")
            except Exception as exc:
                self._append_result(f"  CSV log failed: {exc}", "ERROR")

        # Restart the same run if loop mode is active and Stop was not pressed
        if self._loop_var.get() and not self._stop_requested:
            self._start_run(self._current_run_tests)
            return

        self._run_sel_btn.config(state="normal")
        self._run_all_btn.config(state="normal")
        self._stop_btn.config(state="disabled")

    def _append_run_row(self, path, ts: datetime.datetime) -> None:
        """Append one row to the cumulative CSV log.

        Columns: Timestamp, <test1_name>, <test2_name>, …
        A cell is blank when the test was not part of this run.
        """
        headers = ["Timestamp"] + [tc.name for tc in self._tests]
        result_lookup = {r.test.id: r.status for r in self._run_results}

        row = [ts.strftime("%Y-%m-%dT%H:%M:%S")]
        for tc in self._tests:
            row.append(result_lookup.get(tc.id, ""))

        file_is_new = not path.exists() or path.stat().st_size == 0
        with open(path, "a", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            if file_is_new:
                writer.writerow(headers)
            writer.writerow(row)

    def _append_result(self, text: str, tag: str = "") -> None:
        self._results.config(state="normal")
        self._results.insert("end", text + "\n", tag if tag else ())
        self._results.config(state="disabled")
        self._results.see("end")

    # ------------------------------------------------------------------ #
    #  CSV export
    # ------------------------------------------------------------------ #

    _CSV_HEADERS = [
        "Timestamp", "Name", "Command", "Expected", "Terminator",
        "Timeout_ms", "Status", "Duration_ms", "Actual_Response",
    ]

    def _write_csv(self, path) -> None:
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(self._CSV_HEADERS)
            for i, r in enumerate(self._run_results):
                ts = (self._run_timestamps[i]
                      if i < len(self._run_timestamps)
                      else datetime.datetime.now())
                writer.writerow([
                    ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    r.test.name,
                    r.test.command,
                    r.test.expected,
                    r.test.terminator,
                    r.test.timeout_ms,
                    r.status,
                    f"{r.duration_ms:.1f}",
                    r.actual.replace("\n", " | "),
                ])

    def _export_csv(self) -> None:
        if not self._run_results:
            messagebox.showinfo("Export CSV", "No results to export.")
            return
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV files", "*.csv"), ("All files", "*.*")],
            initialfile=f"test_results_{ts}.csv",
            title="Export test results",
        )
        if not path:
            return
        try:
            self._write_csv(path)
        except OSError as exc:
            messagebox.showerror("Export Failed", str(exc))

    def _clear_results(self) -> None:
        self._results.config(state="normal")
        self._results.delete("1.0", "end")
        self._results.config(state="disabled")
        self._summary_var.set("No results yet")
        self._result_map.clear()
        for iid in self._tree.get_children():
            self._tree.set(iid, "result", "")
            self._tree.item(iid, tags=())

    # ------------------------------------------------------------------ #
    #  Persistence
    # ------------------------------------------------------------------ #

    def _save_tests_to_config(self) -> None:
        self._config["tests"] = [t.to_dict() for t in self._tests]
        self._config.save()

    def _load_tests_from_config(self) -> None:
        raw = self._config.get("tests", [])
        self._tests = [TestCase.from_dict(d) for d in raw if isinstance(d, dict)]
        self._populate_tree()

    # ------------------------------------------------------------------ #
    #  Enable / disable
    # ------------------------------------------------------------------ #

    def set_enabled(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self._run_sel_btn.config(state=state)
        self._run_all_btn.config(state=state)
        if not enabled:
            self._stop_btn.config(state="disabled")
