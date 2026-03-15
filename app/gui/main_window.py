import tkinter as tk
from tkinter import ttk

from app.config import AppConfig, SUITE_CONFIG_PATHS
from app.gui.terminal_pane import TerminalPane
from app.gui.test_suite_panel import TestSuitePanel

_MAX_TERMINALS = 4
_MAX_SUITES = 4


class MainWindow:
    def __init__(self, root: tk.Tk, config: AppConfig) -> None:
        self.root = root
        self._config = config

        self._panes: list = []         # TerminalPane instances
        self._suite_panels: list = []  # TestSuitePanel instances
        self._suite_configs: list = [] # AppConfig per suite (index 0 == self._config)

        self._setup_window()
        self._create_widgets()

        self.root.protocol("WM_DELETE_WINDOW", self._on_closing)

    # ------------------------------------------------------------------ #
    #  Window setup
    # ------------------------------------------------------------------ #

    def _setup_window(self) -> None:
        self.root.title("Serial Terminal")
        self.root.minsize(1100, 680)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

    def _create_widgets(self) -> None:
        self._notebook = ttk.Notebook(self.root)
        self._notebook.grid(row=0, column=0, sticky="nsew", padx=6, pady=4)

        # ── Tab 1: Terminal ──────────────────────────────────────────── #
        tab1 = ttk.Frame(self._notebook)
        tab1.columnconfigure(0, weight=1)
        tab1.rowconfigure(1, weight=1)
        self._notebook.add(tab1, text="  Terminal  ")

        term_toolbar = ttk.Frame(tab1)
        term_toolbar.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 0))

        self._add_term_btn = ttk.Button(
            term_toolbar, text="\uff0b Add Terminal", command=self._add_terminal
        )
        self._add_term_btn.pack(side="left", padx=(0, 4))

        self._remove_term_btn = ttk.Button(
            term_toolbar, text="\uff0d Remove Terminal", command=self._remove_terminal
        )
        self._remove_term_btn.pack(side="left")

        self._term_paned = ttk.PanedWindow(tab1, orient="horizontal")
        self._term_paned.grid(row=1, column=0, sticky="nsew", padx=4, pady=(2, 4))

        n_terms = max(1, min(_MAX_TERMINALS, len(self._config.get("terminals", [{}]))))
        for i in range(n_terms):
            self._add_terminal(restore_index=i)

        self._update_terminal_buttons()

        # ── Tab 2: Test Suite ────────────────────────────────────────── #
        tab2 = ttk.Frame(self._notebook)
        tab2.columnconfigure(0, weight=1)
        tab2.rowconfigure(1, weight=1)
        self._notebook.add(tab2, text="  Test Suite  ")

        suite_toolbar = ttk.Frame(tab2)
        suite_toolbar.grid(row=0, column=0, sticky="ew", padx=4, pady=(2, 0))

        self._add_suite_btn = ttk.Button(
            suite_toolbar, text="\uff0b Add Suite", command=self._add_suite
        )
        self._add_suite_btn.pack(side="left", padx=(0, 4))

        self._remove_suite_btn = ttk.Button(
            suite_toolbar, text="\uff0d Remove Suite", command=self._remove_suite
        )
        self._remove_suite_btn.pack(side="left")

        self._suite_paned = ttk.PanedWindow(tab2, orient="horizontal")
        self._suite_paned.grid(row=1, column=0, sticky="nsew")

        n_suites = max(1, min(_MAX_SUITES, self._config.get("suite_count", 1)))
        for _ in range(n_suites):
            self._add_suite(restore=True)

        self._update_suite_buttons()

    # ------------------------------------------------------------------ #
    #  Terminal pane management
    # ------------------------------------------------------------------ #

    def _add_terminal(self, restore_index: int = None) -> None:
        if len(self._panes) >= _MAX_TERMINALS:
            return

        index = restore_index if restore_index is not None else len(self._panes)

        frame = ttk.LabelFrame(self._term_paned, text=f"Terminal {index + 1}")
        self._term_paned.add(frame, weight=1)

        pane = TerminalPane(frame, self._config, terminal_index=index)
        pane.pack(fill="both", expand=True)

        self._panes.append(pane)
        self._update_terminal_buttons()

        if restore_index is None:
            self._config.set_terminal_count(len(self._panes))
            self._config.save()

    def _remove_terminal(self) -> None:
        if len(self._panes) <= 1:
            return

        self._panes[-1].cleanup()

        children = self._term_paned.panes()
        last_frame = self._term_paned.nametowidget(children[-1])
        self._term_paned.forget(last_frame)
        last_frame.destroy()

        self._panes.pop()
        self._config.set_terminal_count(len(self._panes))
        self._config.save()
        self._update_terminal_buttons()

    def _update_terminal_buttons(self) -> None:
        n = len(self._panes)
        self._add_term_btn.config(state="normal" if n < _MAX_TERMINALS else "disabled")
        self._remove_term_btn.config(state="normal" if n > 1 else "disabled")

    # ------------------------------------------------------------------ #
    #  Suite pane management
    # ------------------------------------------------------------------ #

    def _add_suite(self, restore: bool = False) -> None:
        if len(self._suite_panels) >= _MAX_SUITES:
            return

        idx = len(self._suite_panels)
        # Suite 1 shares the app-level config; suites 2-4 get their own config files
        if idx == 0:
            cfg = self._config
        else:
            cfg = AppConfig.load(SUITE_CONFIG_PATHS[idx])
        self._suite_configs.append(cfg)

        frame = ttk.LabelFrame(self._suite_paned, text=f"Suite {idx + 1}")
        self._suite_paned.add(frame, weight=1)

        panel = TestSuitePanel(
            frame,
            config=cfg,
            suite_index=idx,
            on_collapse_toggle=lambda collapsed, f=frame: self._on_suite_collapse(collapsed, f),
        )
        panel.pack(fill="both", expand=True, padx=2, pady=2)
        self._suite_panels.append(panel)

        self._update_suite_buttons()

        if not restore:
            self._config["suite_count"] = len(self._suite_panels)
            self._config.save()

    def _remove_suite(self) -> None:
        if len(self._suite_panels) <= 1:
            return

        self._suite_panels[-1].cleanup()

        children = self._suite_paned.panes()
        last_frame = self._suite_paned.nametowidget(children[-1])
        self._suite_paned.forget(last_frame)
        last_frame.destroy()

        self._suite_panels.pop()
        self._suite_configs.pop()

        self._config["suite_count"] = len(self._suite_panels)
        self._config.save()
        self._update_suite_buttons()

    def _update_suite_buttons(self) -> None:
        n = len(self._suite_panels)
        self._add_suite_btn.config(state="normal" if n < _MAX_SUITES else "disabled")
        self._remove_suite_btn.config(state="normal" if n > 1 else "disabled")

    def _on_suite_collapse(self, collapsed: bool, frame: ttk.LabelFrame) -> None:
        if collapsed:
            self._suite_paned.pane(frame, weight=0, minsize=50)
        else:
            self._suite_paned.pane(frame, weight=1, minsize=1)
            self._suite_paned.update_idletasks()

    # ------------------------------------------------------------------ #
    #  Shutdown
    # ------------------------------------------------------------------ #

    def _on_closing(self) -> None:
        for panel in self._suite_panels:
            panel.cleanup()
        for pane in self._panes:
            pane.cleanup()
        self._config.set_terminal_count(len(self._panes))
        self._config["suite_count"] = len(self._suite_panels)
        self._config.save()
        self.root.destroy()
