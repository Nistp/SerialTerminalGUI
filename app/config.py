import json
import pathlib
import sys

CONFIG_PATH = pathlib.Path(__file__).parent.parent / "config.json"

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
    "tests": [],
}


class AppConfig:
    def __init__(self, data: dict) -> None:
        self._data = data

    @classmethod
    def load(cls) -> "AppConfig":
        data = dict(DEFAULTS)
        try:
            raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data.update(raw)
        except Exception:
            pass
        return cls(data)

    def save(self) -> None:
        try:
            CONFIG_PATH.write_text(
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
