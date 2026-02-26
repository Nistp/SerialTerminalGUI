import json
import pathlib
import sys

_ROOT = pathlib.Path(__file__).parent.parent
CONFIG_PATH   = _ROOT / "config.json"    # legacy — kept for migration only
CONFIG_1_PATH = _ROOT / "config_1.json"  # Suite 1
CONFIG_2_PATH = _ROOT / "config_2.json"  # Suite 2

BAUD_RATES = [300, 1200, 2400, 4800, 9600, 19200, 38400, 57600,
              115200, 230400, 460800, 921600]

PARITIES = {"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"}
PARITIES_INV = {v: k for k, v in PARITIES.items()}

STOPBITS = {"1": 1, "1.5": 1.5, "2": 2}
STOPBITS_INV = {v: k for k, v in STOPBITS.items()}

LINE_ENDINGS = {"None": b"", "CR": b"\r", "LF": b"\n", "CRLF": b"\r\n"}

DEFAULTS: dict = {
    "port": "",
    "baud": 115200,
    "parity": "N",
    "databits": 8,
    "stopbits": 1,
    "line_ending": "CRLF",
    "log_dir": "",
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
    "suite_2_visible": False,
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
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
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

    def effective_log_dir(self) -> pathlib.Path:
        d = self._data.get("log_dir", "")
        if d:
            return pathlib.Path(d)
        return pathlib.Path.home() / "serial_logs"
