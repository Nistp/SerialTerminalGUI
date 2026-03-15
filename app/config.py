import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
CONFIG_PATH   = _ROOT / "config.json"    # legacy — kept for migration only
CONFIG_1_PATH = _ROOT / "config_1.json"  # Suite 1 / app-level config
CONFIG_2_PATH = _ROOT / "config_2.json"  # Suite 2
CONFIG_3_PATH = _ROOT / "config_3.json"  # Suite 3
CONFIG_4_PATH = _ROOT / "config_4.json"  # Suite 4

SUITE_CONFIG_PATHS = [CONFIG_1_PATH, CONFIG_2_PATH, CONFIG_3_PATH, CONFIG_4_PATH]

BAUD_RATES = [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600,
              115200, 230400, 460800, 921600]

PARITIES = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}
PARITIES_INV = {v: k for k, v in PARITIES.items()}

STOPBITS = {"1": 1, "1.5": 1.5, "2": 2}
STOPBITS_INV = {v: k for k, v in STOPBITS.items()}

LINE_ENDINGS = {"None": b"", "CR": b"\r", "LF": b"\n", "CRLF": b"\r\n"}

TERMINAL_DEFAULTS: dict = {
    "port":        "",
    "baud":        115200,
    "parity":      "N",
    "databits":    8,
    "stopbits":    1,
    "line_ending": "CRLF",
    "log_dir":     "",
}

_TERMINAL_KEYS = frozenset(TERMINAL_DEFAULTS.keys())

DEFAULTS: dict = {
    "terminals": [dict(TERMINAL_DEFAULTS)],  # list of per-terminal connection settings
    "autoscroll": True,
    "show_timestamp": True,
    "font_size": 10,
    "history_size": 100,
    "poll_interval_ms": 50,
    "max_lines": 5000,
    "test_delay_ms": 200,
    "loop_interval_s": 0,
    "tests": [],
    "trigger_port": "",
    "trigger_baud": 9600,
    "suite_port":        "",
    "suite_baud":        115200,
    "suite_parity":      "N",
    "suite_line_ending": "CRLF",
    "suite_count": 1,  # number of suite panes open (1–4)
}


class AppConfig:
    def __init__(self, data: dict, path: pathlib.Path) -> None:
        self._data = data
        self._path = path

    @classmethod
    def load(cls, path: pathlib.Path = None) -> "AppConfig":
        if path is None:
            path = CONFIG_1_PATH
            # One-time migration: rename legacy config.json → config_1.json
            if CONFIG_PATH.exists() and not CONFIG_1_PATH.exists():
                try:
                    CONFIG_PATH.rename(CONFIG_1_PATH)
                except Exception as exc:
                    print(f"[config] migration failed: {exc}", file=sys.stderr)

        data = dict(DEFAULTS)
        data["terminals"] = [dict(TERMINAL_DEFAULTS)]  # fresh list, not shared with DEFAULTS
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
                # Migrate old flat terminal keys → terminals list (runs once per old config)
                if "terminals" not in raw:
                    flat_keys = tuple(TERMINAL_DEFAULTS.keys())
                    terminal_0 = dict(TERMINAL_DEFAULTS)
                    for k in flat_keys:
                        if k in raw:
                            terminal_0[k] = raw[k]
                    data["terminals"] = [terminal_0]
                    for k in flat_keys:
                        data.pop(k, None)
                # Migrate suite_2_visible → suite_count
                if "suite_2_visible" in raw and "suite_count" not in raw:
                    data["suite_count"] = 2 if raw["suite_2_visible"] else 1
                data.pop("suite_2_visible", None)
        except Exception:
            pass
        return cls(data, path)

    def save(self) -> None:
        try:
            self._path.write_text(
                json.dumps(self._data, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"[config] save failed: {exc}", file=sys.stderr)

    def __getitem__(self, key):
        return self._data[key]

    def __setitem__(self, key, value) -> None:
        self._data[key] = value

    def get(self, key, default=None):
        return self._data.get(key, default)

    def get_terminal_config(self, index: int) -> dict:
        """Return a merged copy of TERMINAL_DEFAULTS + stored settings for terminal index."""
        terminals = self._data.get("terminals", [])
        cfg = dict(TERMINAL_DEFAULTS)
        if index < len(terminals):
            cfg.update(terminals[index])
        return cfg

    def save_terminal_config(self, index: int, values: dict) -> None:
        """Write keys from values into terminals[index], extending the list if needed."""
        terminals = self._data.setdefault("terminals", [])
        while len(terminals) <= index:
            terminals.append(dict(TERMINAL_DEFAULTS))
        terminals[index].update(values)

    def set_terminal_count(self, count: int) -> None:
        """Trim or extend the terminals list to exactly count entries."""
        terminals = self._data.setdefault("terminals", [])
        while len(terminals) < count:
            terminals.append(dict(TERMINAL_DEFAULTS))
        del terminals[count:]

    def effective_log_dir(self) -> pathlib.Path:
        # Used by Suite 2 (config_2.json) which may still carry a flat log_dir key.
        d = self._data.get("log_dir", "")
        if d:
            return pathlib.Path(d)
        return pathlib.Path.home() / "serial_logs"

    def effective_log_dir_for(self, terminal_cfg: dict) -> pathlib.Path:
        """Resolve log dir for a per-terminal config dict."""
        d = terminal_cfg.get("log_dir", "")
        if d:
            return pathlib.Path(d)
        return pathlib.Path.home() / "serial_logs"
