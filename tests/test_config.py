"""Tests for app/config.py — AppConfig load, save, migration, and helpers."""
import json
import pathlib

import pytest

from app.config import (
    TERMINAL_DEFAULTS,
    DEFAULTS,
    LINE_ENDINGS,
    BAUD_RATES,
    PARITIES,
    AppConfig,
)


def _write_json(path: pathlib.Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_line_endings_none(self):
        assert LINE_ENDINGS["None"] == b""

    def test_line_endings_cr(self):
        assert LINE_ENDINGS["CR"] == b"\r"

    def test_line_endings_lf(self):
        assert LINE_ENDINGS["LF"] == b"\n"

    def test_line_endings_crlf(self):
        assert LINE_ENDINGS["CRLF"] == b"\r\n"

    def test_baud_rates_contains_common(self):
        for rate in (9600, 115200, 921600):
            assert rate in BAUD_RATES

    def test_parities_keys(self):
        assert set(PARITIES.keys()) == {"None", "Even", "Odd", "Mark", "Space"}

    def test_terminal_defaults_has_required_keys(self):
        for key in ("port", "baud", "parity", "databits", "stopbits", "line_ending", "log_dir"):
            assert key in TERMINAL_DEFAULTS


# ---------------------------------------------------------------------------
# AppConfig.load — fresh (no file)
# ---------------------------------------------------------------------------

class TestAppConfigLoadFresh:
    def test_load_missing_file_uses_defaults(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "nonexistent.json")
        assert cfg["autoscroll"] == DEFAULTS["autoscroll"]
        assert cfg["font_size"] == DEFAULTS["font_size"]
        assert cfg["suite_count"] == 1

    def test_load_missing_file_has_terminals_list(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "nonexistent.json")
        assert isinstance(cfg["terminals"], list)
        assert len(cfg["terminals"]) == 1

    def test_load_invalid_json_uses_defaults(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("not json", encoding="utf-8")
        cfg = AppConfig.load(p)
        assert cfg["suite_count"] == 1

    def test_load_non_dict_json_uses_defaults(self, tmp_path):
        p = tmp_path / "bad.json"
        p.write_text("[1, 2, 3]", encoding="utf-8")
        cfg = AppConfig.load(p)
        assert cfg["autoscroll"] == DEFAULTS["autoscroll"]


# ---------------------------------------------------------------------------
# AppConfig.load — normal round-trip
# ---------------------------------------------------------------------------

class TestAppConfigLoadNormal:
    def test_load_reads_existing_values(self, tmp_path):
        p = tmp_path / "cfg.json"
        _write_json(p, {"autoscroll": False, "font_size": 14,
                        "terminals": [dict(TERMINAL_DEFAULTS)]})
        cfg = AppConfig.load(p)
        assert cfg["autoscroll"] is False
        assert cfg["font_size"] == 14

    def test_load_merges_missing_keys_with_defaults(self, tmp_path):
        p = tmp_path / "cfg.json"
        _write_json(p, {"font_size": 12})
        cfg = AppConfig.load(p)
        assert cfg["autoscroll"] == DEFAULTS["autoscroll"]
        assert cfg["suite_count"] == DEFAULTS["suite_count"]

    def test_load_stores_path(self, tmp_path):
        p = tmp_path / "cfg.json"
        cfg = AppConfig.load(p)
        assert cfg._path == p

    def test_load_suite_count_respected(self, tmp_path):
        p = tmp_path / "cfg.json"
        _write_json(p, {"suite_count": 3})
        cfg = AppConfig.load(p)
        assert cfg["suite_count"] == 3


# ---------------------------------------------------------------------------
# AppConfig.load — migrations
# ---------------------------------------------------------------------------

class TestAppConfigMigrations:
    def test_flat_terminal_keys_moved_to_terminals_0(self, tmp_path):
        """Old configs with flat port/baud/etc. keys get moved into terminals[0]."""
        p = tmp_path / "cfg.json"
        _write_json(p, {"port": "COM5", "baud": 19200, "parity": "E",
                        "databits": 8, "stopbits": 1,
                        "line_ending": "CR", "log_dir": "/tmp/logs"})
        cfg = AppConfig.load(p)
        t0 = cfg["terminals"][0]
        assert t0["port"] == "COM5"
        assert t0["baud"] == 19200
        assert t0["parity"] == "E"
        assert t0["log_dir"] == "/tmp/logs"

    def test_flat_keys_removed_from_root_after_migration(self, tmp_path):
        p = tmp_path / "cfg.json"
        _write_json(p, {"port": "COM5", "baud": 19200, "parity": "N",
                        "databits": 8, "stopbits": 1,
                        "line_ending": "CRLF", "log_dir": ""})
        cfg = AppConfig.load(p)
        assert "port" not in cfg._data
        assert "baud" not in cfg._data

    def test_suite_2_visible_true_becomes_suite_count_2(self, tmp_path):
        p = tmp_path / "cfg.json"
        _write_json(p, {"suite_2_visible": True})
        cfg = AppConfig.load(p)
        assert cfg["suite_count"] == 2

    def test_suite_2_visible_false_becomes_suite_count_1(self, tmp_path):
        p = tmp_path / "cfg.json"
        _write_json(p, {"suite_2_visible": False})
        cfg = AppConfig.load(p)
        assert cfg["suite_count"] == 1

    def test_suite_2_visible_stripped_from_data(self, tmp_path):
        p = tmp_path / "cfg.json"
        _write_json(p, {"suite_2_visible": True})
        cfg = AppConfig.load(p)
        assert "suite_2_visible" not in cfg._data

    def test_explicit_suite_count_overrides_suite_2_visible(self, tmp_path):
        """If suite_count already exists, suite_2_visible migration is skipped."""
        p = tmp_path / "cfg.json"
        _write_json(p, {"suite_2_visible": True, "suite_count": 3})
        cfg = AppConfig.load(p)
        assert cfg["suite_count"] == 3

    def test_terminals_key_present_skips_flat_migration(self, tmp_path):
        """When 'terminals' key exists in file, flat keys at root are not migrated."""
        p = tmp_path / "cfg.json"
        _write_json(p, {"terminals": [{"port": "COM1", "baud": 115200,
                                       "parity": "N", "databits": 8,
                                       "stopbits": 1, "line_ending": "CRLF",
                                       "log_dir": ""}],
                        "port": "COM99"})
        cfg = AppConfig.load(p)
        assert cfg["terminals"][0]["port"] == "COM1"


# ---------------------------------------------------------------------------
# AppConfig.save
# ---------------------------------------------------------------------------

class TestAppConfigSave:
    def test_save_creates_file(self, tmp_path):
        p = tmp_path / "cfg.json"
        cfg = AppConfig.load(p)
        cfg.save()
        assert p.exists()

    def test_save_and_reload_preserves_values(self, tmp_path):
        p = tmp_path / "cfg.json"
        cfg = AppConfig.load(p)
        cfg["font_size"] = 16
        cfg.save()
        cfg2 = AppConfig.load(p)
        assert cfg2["font_size"] == 16

    def test_save_writes_valid_json(self, tmp_path):
        p = tmp_path / "cfg.json"
        cfg = AppConfig.load(p)
        cfg.save()
        data = json.loads(p.read_text(encoding="utf-8"))
        assert isinstance(data, dict)

    def test_save_preserves_terminal_list(self, tmp_path):
        p = tmp_path / "cfg.json"
        cfg = AppConfig.load(p)
        cfg.save_terminal_config(0, {"port": "COM8"})
        cfg.save()
        cfg2 = AppConfig.load(p)
        assert cfg2["terminals"][0]["port"] == "COM8"


# ---------------------------------------------------------------------------
# Dict-like access
# ---------------------------------------------------------------------------

class TestAppConfigAccess:
    def test_getitem_returns_value(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        assert cfg["suite_count"] == 1

    def test_setitem_updates_value(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg["suite_count"] = 4
        assert cfg["suite_count"] == 4

    def test_get_missing_key_returns_default(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        assert cfg.get("no_such_key", "fallback") == "fallback"

    def test_get_existing_key_returns_value(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        assert cfg.get("suite_count") == 1

    def test_get_missing_key_no_default_returns_none(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        assert cfg.get("no_such_key") is None


# ---------------------------------------------------------------------------
# get_terminal_config
# ---------------------------------------------------------------------------

class TestGetTerminalConfig:
    def test_out_of_range_index_returns_defaults(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        t = cfg.get_terminal_config(99)
        assert t["baud"] == TERMINAL_DEFAULTS["baud"]
        assert t["port"] == TERMINAL_DEFAULTS["port"]

    def test_index_0_returns_stored_values(self, tmp_path):
        p = tmp_path / "c.json"
        _write_json(p, {"terminals": [{"port": "COM7", "baud": 57600,
                                       "parity": "N", "databits": 8,
                                       "stopbits": 1, "line_ending": "CRLF",
                                       "log_dir": ""}]})
        cfg = AppConfig.load(p)
        t = cfg.get_terminal_config(0)
        assert t["port"] == "COM7"
        assert t["baud"] == 57600

    def test_partial_stored_data_merged_with_defaults(self, tmp_path):
        p = tmp_path / "c.json"
        _write_json(p, {"terminals": [{"port": "COM2"}]})
        cfg = AppConfig.load(p)
        t = cfg.get_terminal_config(0)
        assert t["port"] == "COM2"
        assert t["baud"] == TERMINAL_DEFAULTS["baud"]

    def test_returns_copy_mutation_does_not_affect_stored(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        t1 = cfg.get_terminal_config(0)
        t1["port"] = "MUTATED"
        t2 = cfg.get_terminal_config(0)
        assert t2["port"] != "MUTATED"


# ---------------------------------------------------------------------------
# save_terminal_config
# ---------------------------------------------------------------------------

class TestSaveTerminalConfig:
    def test_write_to_index_0(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.save_terminal_config(0, {"port": "COM10", "baud": 38400})
        assert cfg["terminals"][0]["port"] == "COM10"
        assert cfg["terminals"][0]["baud"] == 38400

    def test_extends_list_for_new_index(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.save_terminal_config(2, {"port": "COM3"})
        assert len(cfg["terminals"]) >= 3
        assert cfg["terminals"][2]["port"] == "COM3"

    def test_gap_entries_filled_with_terminal_defaults(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.save_terminal_config(2, {"port": "COM9"})
        t1 = cfg["terminals"][1]
        assert t1["baud"] == TERMINAL_DEFAULTS["baud"]

    def test_updates_existing_entry(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.save_terminal_config(0, {"port": "COM1"})
        cfg.save_terminal_config(0, {"port": "COM2"})
        assert cfg["terminals"][0]["port"] == "COM2"


# ---------------------------------------------------------------------------
# set_terminal_count
# ---------------------------------------------------------------------------

class TestSetTerminalCount:
    def test_extend_to_three(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.set_terminal_count(3)
        assert len(cfg["terminals"]) == 3

    def test_trim_to_two(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.set_terminal_count(4)
        cfg.set_terminal_count(2)
        assert len(cfg["terminals"]) == 2

    def test_trim_keeps_first_entry_intact(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.save_terminal_config(0, {"port": "COM1"})
        cfg.set_terminal_count(3)
        cfg.set_terminal_count(1)
        assert len(cfg["terminals"]) == 1
        assert cfg["terminals"][0]["port"] == "COM1"

    def test_new_entries_have_terminal_defaults(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.set_terminal_count(2)
        t1 = cfg["terminals"][1]
        assert t1["baud"] == TERMINAL_DEFAULTS["baud"]
        assert t1["port"] == TERMINAL_DEFAULTS["port"]

    def test_set_count_to_same_is_noop(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        cfg.set_terminal_count(1)
        assert len(cfg["terminals"]) == 1


# ---------------------------------------------------------------------------
# effective_log_dir / effective_log_dir_for
# ---------------------------------------------------------------------------

class TestEffectiveLogDir:
    def test_empty_string_returns_home_serial_logs(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        assert cfg.effective_log_dir() == pathlib.Path.home() / "serial_logs"

    def test_custom_path_returned_as_path_object(self, tmp_path):
        p = tmp_path / "c.json"
        # Include 'terminals' so migration does not move log_dir into terminals[0]
        _write_json(p, {"log_dir": str(tmp_path / "mylogs"),
                        "terminals": [dict(TERMINAL_DEFAULTS)]})
        cfg = AppConfig.load(p)
        assert cfg.effective_log_dir() == tmp_path / "mylogs"

    def test_for_empty_log_dir_returns_home_serial_logs(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        assert cfg.effective_log_dir_for({"log_dir": ""}) == pathlib.Path.home() / "serial_logs"

    def test_for_custom_path_returns_it(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        result = cfg.effective_log_dir_for({"log_dir": "/custom/logs"})
        assert result == pathlib.Path("/custom/logs")

    def test_for_missing_key_returns_default(self, tmp_path):
        cfg = AppConfig.load(tmp_path / "c.json")
        assert cfg.effective_log_dir_for({}) == pathlib.Path.home() / "serial_logs"
