"""Tests for ocdu.config (defaults, JSON loading, references, persistence)."""

from __future__ import annotations
import json
import os
from pathlib import Path
import pytest
from ocdu.config import (
    Config,
    _parse_config_file,
    _read_raw_config,
    config as module_config,
    load_config,
    save_ui_overrides,
)

def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")
    return path

class TestLoadConfig:

    def test_missing_file_uses_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "absent.json")
        assert cfg.get("OPENCODE_DATA_DIR") == "~/.local/share/opencode"
        assert cfg.get_int("LOG_RETENTION_DAYS") == 30
        assert cfg.theme == "textual-dark"

    def test_malformed_json_falls_back(self, tmp_path):
        path = _write(tmp_path / "cfg.json", "{not json")
        assert load_config(path).get("OPENCODE_DATA_DIR") == "~/.local/share/opencode"

    def test_non_dict_json_falls_back(self, tmp_path):
        for payload in ("[1, 2]", '"string"', "42"):
            path = _write(tmp_path / "cfg.json", payload)
            assert load_config(path).get("BACKUP_KEEP") == "3"

    def test_partial_override_merges(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"BACKUP_KEEP": "9"})
        cfg = load_config(path)
        assert cfg.backup_keep == 9
        assert cfg.get("OPENCODE_DATA_DIR") == "~/.local/share/opencode"

    def test_values_are_stringified(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"BACKUP_KEEP": 5, "FLAG": True})
        cfg = load_config(path)
        assert cfg.get("BACKUP_KEEP") == "5"
        assert cfg.get("FLAG") == "True"

class TestReferences:

    def test_default_backup_reference(self, tmp_path):
        cfg = load_config(tmp_path / "absent.json")
        assert cfg.get("BACKUP_DIR") == "~/.local/share/opencode/backups"

    def test_chained_references(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"A": "/a", "B": "${A}/b", "C": "${B}/c"})
        cfg = load_config(path)
        assert cfg.get("C") == "/a/b/c"

    def test_missing_reference_becomes_empty(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"X": "${NOPE}/z"})
        assert load_config(path).get("X") == "/z"

    def test_self_reference_terminates(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"A": "${A}x"})
        value = load_config(path).get("A")
        assert isinstance(value, str)

    def test_cycle_terminates(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"A": "${B}", "B": "${A}"})
        assert isinstance(load_config(path).get("A"), str)

class TestTypedAccessors:

    def test_get_empty_value_returns_fallback(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"THEME": ""})
        assert load_config(path).get("THEME", "fallback") == "fallback"
        assert load_config(path).get("MISSING", "fallback") == "fallback"

    @pytest.mark.parametrize(
        "raw,expected",
        [("5", 5), (" 7 ", 7), ("-4", -4), ("abc", 0), ("3.14", 0), ("", 0)],
    )
    def test_get_int(self, tmp_path, raw, expected):
        path = _write(tmp_path / "cfg.json", {"N": raw})
        assert load_config(path).get_int("N", 0) == expected

    def test_backup_keep_never_below_one(self, tmp_path):
        for raw in ("0", "-5"):
            path = _write(tmp_path / "cfg.json", {"BACKUP_KEEP": raw})
            assert load_config(path).backup_keep == 1

    def test_timeout_invalid_falls_back(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"OPENCODE_CLI_TIMEOUT": "abc"})
        assert load_config(path).opencode_cli_timeout == 120

    def test_scalar_defaults(self, tmp_path):
        cfg = load_config(tmp_path / "absent.json")
        assert cfg.tui_refresh_seconds == 0
        assert cfg.log_retention_days == 30
        assert cfg.opencode_bin == "opencode"

    def test_dist_dir_default_and_override(self, tmp_path):
        assert load_config(tmp_path / "absent.json").dist_dir == Path("dist")
        path = _write(tmp_path / "cfg.json", {"DIST_DIR": "  release  "})
        assert load_config(path).dist_dir == Path("release")

class TestPaths:

    def test_tilde_expansion(self, tmp_path, monkeypatch):
        monkeypatch.setattr(os.path, "expanduser", lambda value: value.replace("~", "/HOME"))
        cfg = load_config(tmp_path / "absent.json")
        assert cfg.data_dir == Path("/HOME/.local/share/opencode")
        assert cfg.backup_dir == Path("/HOME/.local/share/opencode/backups")

    def test_db_path_uses_data_dir_and_file(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"OPENCODE_DATA_DIR": "/data", "OPENCODE_DB_FILE": "x.db"})
        assert load_config(path).db_path == Path("/data/x.db")

    def test_db_path_default_file(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"OPENCODE_DATA_DIR": "/data"})
        assert load_config(path).db_path == Path("/data/opencode.db")

class TestRawReaders:

    def test_read_raw_config_non_dict(self, tmp_path):
        path = _write(tmp_path / "cfg.json", "[1, 2]")
        assert _read_raw_config(path) == {}

    def test_read_raw_config_missing(self, tmp_path):
        assert _read_raw_config(tmp_path / "absent.json") == {}

    def test_parse_config_file_stringifies(self, tmp_path):
        path = _write(tmp_path / "cfg.json", {"A": 1, "B": None})
        assert _parse_config_file(path) == {"A": "1", "B": "None"}

class TestSaveOverrides:

    def test_creates_file_and_parents(self, tmp_path):
        target = tmp_path / "nested" / "ocdu-ui.json"
        returned = save_ui_overrides({"THEME": "flexoki"}, target)
        assert returned == target
        assert json.loads(target.read_text(encoding="utf-8")) == {"THEME": "flexoki"}

    def test_merges_existing_keys(self, tmp_path):
        target = _write(tmp_path / "cfg.json", {"BACKUP_KEEP": "9"})
        save_ui_overrides({"THEME": "flexoki"}, target)
        data = json.loads(target.read_text(encoding="utf-8"))
        assert data == {"BACKUP_KEEP": "9", "THEME": "flexoki"}

    def test_preserves_unicode(self, tmp_path):
        target = tmp_path / "cfg.json"
        save_ui_overrides({"THEME": "Türkçe"}, target)
        assert "Türkçe" in target.read_text(encoding="utf-8")

    def test_overwrites_malformed_file(self, tmp_path):
        target = _write(tmp_path / "cfg.json", "{broken")
        save_ui_overrides({"THEME": "x"}, target)
        assert json.loads(target.read_text(encoding="utf-8")) == {"THEME": "x"}

class TestModuleSingleton:

    def test_is_config_instance(self):
        assert isinstance(module_config, Config)
