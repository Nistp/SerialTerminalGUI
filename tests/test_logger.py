"""Tests for app/logger.py — SessionLogger file creation, format, and lifecycle."""
import datetime
import pathlib
import re

import pytest

from app.serial_handler import Direction, TerminalMessage
from app.logger import SessionLogger


# ---------------------------------------------------------------------------
# Initial state
# ---------------------------------------------------------------------------

class TestSessionLoggerInitialState:
    def test_not_open_initially(self):
        logger = SessionLogger()
        assert not logger.is_open

    def test_current_log_path_is_none_initially(self):
        logger = SessionLogger()
        assert logger.current_log_path is None


# ---------------------------------------------------------------------------
# open_session
# ---------------------------------------------------------------------------

class TestOpenSession:
    def test_is_open_after_open_session(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        assert logger.is_open
        logger.close_session()

    def test_returns_path_object(self, tmp_path):
        logger = SessionLogger()
        p = logger.open_session(tmp_path)
        assert isinstance(p, pathlib.Path)
        logger.close_session()

    def test_file_is_created(self, tmp_path):
        logger = SessionLogger()
        p = logger.open_session(tmp_path)
        assert p.exists()
        logger.close_session()

    def test_filename_matches_session_pattern(self, tmp_path):
        logger = SessionLogger()
        p = logger.open_session(tmp_path)
        assert re.match(r"session_\d{8}_\d{6}\.log", p.name)
        logger.close_session()

    def test_current_log_path_set(self, tmp_path):
        logger = SessionLogger()
        p = logger.open_session(tmp_path)
        assert logger.current_log_path == p
        logger.close_session()

    def test_creates_missing_log_directory(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        logger = SessionLogger()
        p = logger.open_session(nested)
        assert p.exists()
        logger.close_session()

    def test_file_is_in_specified_directory(self, tmp_path):
        logger = SessionLogger()
        p = logger.open_session(tmp_path)
        assert p.parent == tmp_path
        logger.close_session()


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------

class TestWrite:
    def _make_msg(self, direction: Direction, text: str) -> TerminalMessage:
        ts = datetime.datetime(2024, 3, 15, 10, 30, 45, 123000)
        return TerminalMessage(direction, text, timestamp=ts)

    def test_write_creates_line_in_file(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        msg = self._make_msg(Direction.TX, "AT+CSQ")
        logger.write(msg)
        logger.close_session()

        content = (tmp_path / list(tmp_path.iterdir())[0].name).read_text(encoding="utf-8")
        assert "AT+CSQ" in content

    def test_write_includes_direction_tx(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.write(self._make_msg(Direction.TX, "cmd"))
        logger.close_session()

        content = next(tmp_path.iterdir()).read_text(encoding="utf-8")
        assert "TX" in content

    def test_write_includes_direction_rx(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.write(self._make_msg(Direction.RX, "response"))
        logger.close_session()

        content = next(tmp_path.iterdir()).read_text(encoding="utf-8")
        assert "RX" in content

    def test_write_includes_iso_timestamp(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.write(self._make_msg(Direction.INFO, "info"))
        logger.close_session()

        content = next(tmp_path.iterdir()).read_text(encoding="utf-8")
        # ISO timestamp contains date fragment 2024-03-15
        assert "2024-03-15" in content

    def test_write_format_contains_all_parts(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.write(self._make_msg(Direction.RX, "OK"))
        logger.close_session()

        content = next(tmp_path.iterdir()).read_text(encoding="utf-8")
        # Line should contain timestamp, direction in brackets, and text
        assert "[RX" in content
        assert "OK" in content

    def test_write_multiple_messages_appended(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.write(self._make_msg(Direction.TX, "first"))
        logger.write(self._make_msg(Direction.RX, "second"))
        logger.close_session()

        content = next(tmp_path.iterdir()).read_text(encoding="utf-8")
        assert "first" in content
        assert "second" in content

    def test_write_when_not_open_is_silent_noop(self):
        logger = SessionLogger()
        msg = self._make_msg(Direction.TX, "ignored")
        logger.write(msg)  # must not raise

    def test_write_error_direction(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.write(self._make_msg(Direction.ERROR, "Port error"))
        logger.close_session()

        content = next(tmp_path.iterdir()).read_text(encoding="utf-8")
        assert "ERROR" in content
        assert "Port error" in content

    def test_write_empty_text(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.write(self._make_msg(Direction.RX, ""))
        logger.close_session()
        # Should not raise — empty text is valid


# ---------------------------------------------------------------------------
# close_session
# ---------------------------------------------------------------------------

class TestCloseSession:
    def test_is_not_open_after_close(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.close_session()
        assert not logger.is_open

    def test_current_log_path_is_none_after_close(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.close_session()
        assert logger.current_log_path is None

    def test_close_when_not_open_is_safe(self):
        logger = SessionLogger()
        logger.close_session()  # must not raise

    def test_close_twice_is_safe(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.close_session()
        logger.close_session()  # must not raise

    def test_write_after_close_is_silent_noop(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.close_session()
        msg = TerminalMessage(Direction.TX, "after close")
        logger.write(msg)  # must not raise

    def test_can_reopen_after_close(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        logger.close_session()
        p2 = logger.open_session(tmp_path)
        assert logger.is_open
        assert p2.exists()
        logger.close_session()

    def test_file_content_flushed_before_close(self, tmp_path):
        logger = SessionLogger()
        logger.open_session(tmp_path)
        ts = datetime.datetime(2024, 1, 1, 0, 0, 0)
        logger.write(TerminalMessage(Direction.TX, "flush_check", timestamp=ts))
        logger.close_session()

        content = next(tmp_path.iterdir()).read_text(encoding="utf-8")
        assert "flush_check" in content
