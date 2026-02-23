import pathlib
import sys
from datetime import datetime
from typing import Optional

from app.serial_handler import TerminalMessage


class SessionLogger:
    LOG_LINE_FMT = "{timestamp} [{direction:<5s}] {text}\n"

    def __init__(self) -> None:
        self._file = None
        self._path: Optional[pathlib.Path] = None

    @property
    def is_open(self) -> bool:
        return self._file is not None

    @property
    def current_log_path(self) -> Optional[pathlib.Path]:
        return self._path

    def open_session(self, log_dir: pathlib.Path) -> pathlib.Path:
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self._path = log_dir / f"session_{timestamp}.log"
        self._file = open(
            self._path, "a", encoding="utf-8", errors="replace", newline=""
        )
        return self._path

    def write(self, msg: TerminalMessage) -> None:
        if self._file is None:
            return
        try:
            line = self.LOG_LINE_FMT.format(
                timestamp=msg.timestamp.isoformat(timespec="milliseconds"),
                direction=msg.direction.value,
                text=msg.text,
            )
            self._file.write(line)
            self._file.flush()
        except Exception as exc:
            print(f"[logger] write failed: {exc}", file=sys.stderr)

    def close_session(self) -> None:
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            except Exception:
                pass
            self._file = None
            self._path = None
