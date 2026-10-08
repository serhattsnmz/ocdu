"""Tests for ocdu.opencode (CLI wrapper)."""

from __future__ import annotations
import subprocess
from pathlib import Path
from types import SimpleNamespace
import pytest
import ocdu.opencode as opencode
from ocdu.opencode import CliResult, _working_dir, delete_session, export_session_json, resolve_bin, run_cli

def _completed(returncode: int = 0, stdout: str = "", stderr: str = ""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)

class TestResolveBin:

    def test_uses_which_when_available(self, config_factory, monkeypatch):
        monkeypatch.setattr(opencode.shutil, "which", lambda _name: "/usr/bin/opencode")
        assert resolve_bin(config_factory()) == "/usr/bin/opencode"

    def test_falls_back_to_configured_name(self, config_factory, monkeypatch):
        monkeypatch.setattr(opencode.shutil, "which", lambda _name: None)
        assert resolve_bin(config_factory()) == "opencode"

class TestRunCli:

    def test_success_records_args(self, config_factory, monkeypatch):
        captured = {}
        monkeypatch.setattr(opencode.shutil, "which", lambda _name: None)

        def fake_run(args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs
            return _completed(0, "out", "err")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_cli(config_factory(), ["session", "delete", "s1"])
        assert result.ok is True
        assert result.stdout == "out"
        assert result.args[0] == "opencode"
        assert result.args[1:] == ["session", "delete", "s1"]

    def test_file_not_found(self, config_factory, monkeypatch):
        def fake_run(*_args, **_kwargs):
            raise FileNotFoundError("nope")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_cli(config_factory(), ["x"])
        assert result.returncode == 127
        assert result.ok is False

    def test_timeout(self, config_factory, monkeypatch):
        def fake_run(*_args, **_kwargs):
            raise subprocess.TimeoutExpired(cmd=["opencode"], timeout=1, output="partial")

        monkeypatch.setattr(subprocess, "run", fake_run)
        result = run_cli(config_factory(), ["x"])
        assert result.returncode == 124
        assert result.stdout == "partial"
        assert "timed out" in result.stderr

    def test_custom_timeout_and_cwd(self, config_factory, monkeypatch, tmp_path):
        captured = {}

        def fake_run(args, **kwargs):
            captured.update(kwargs)
            return _completed()

        monkeypatch.setattr(subprocess, "run", fake_run)
        run_cli(config_factory(OPENCODE_CLI_TIMEOUT="42"), ["x"], cwd=tmp_path)
        assert captured["timeout"] == 42
        assert captured["cwd"] == str(tmp_path)

class TestWorkingDir:

    def test_existing_directory(self, config_factory, tmp_path):
        assert _working_dir(config_factory(), str(tmp_path)) == tmp_path

    def test_missing_directory_falls_back_to_data_dir(self, config_factory, tmp_path):
        cfg = config_factory()
        assert _working_dir(cfg, str(tmp_path / "nope")) == cfg.data_dir

    def test_none_falls_back_to_data_dir(self, config_factory):
        cfg = config_factory()
        assert _working_dir(cfg, None) == cfg.data_dir

class TestSessionCommands:

    def test_delete_session_args(self, config_factory, tmp_path, monkeypatch):
        captured = {}

        def fake_run_cli(_config, args, *, cwd=None, timeout=None):
            captured["args"] = args
            captured["cwd"] = cwd
            return CliResult([], 0, "", "")

        monkeypatch.setattr(opencode, "run_cli", fake_run_cli)
        delete_session(config_factory(), "s1", str(tmp_path))
        assert captured["args"] == ["session", "delete", "s1"]
        assert captured["cwd"] == tmp_path

    def test_export_uses_long_timeout(self, config_factory, tmp_path, monkeypatch):
        captured = {}

        def fake_run_cli(_config, args, *, cwd=None, timeout=None):
            captured["args"] = args
            captured["timeout"] = timeout
            return CliResult([], 0, "{}", "")

        monkeypatch.setattr(opencode, "run_cli", fake_run_cli)
        export_session_json(config_factory(OPENCODE_CLI_TIMEOUT="10"), "s1", str(tmp_path))
        assert captured["args"] == ["export", "s1"]
        assert captured["timeout"] == 300

    def test_export_keeps_larger_timeout(self, config_factory, tmp_path, monkeypatch):
        captured = {}

        def fake_run_cli(_config, args, *, cwd=None, timeout=None):
            captured["timeout"] = timeout
            return CliResult([], 0, "{}", "")

        monkeypatch.setattr(opencode, "run_cli", fake_run_cli)
        export_session_json(config_factory(OPENCODE_CLI_TIMEOUT="500"), "s1", str(tmp_path))
        assert captured["timeout"] == 500

    def test_existing_dir_is_used_as_cwd(self, config_factory, tmp_path, monkeypatch):
        captured = {}

        def fake_run_cli(_config, args, *, cwd=None, timeout=None):
            captured["cwd"] = cwd
            return CliResult([], 0, "", "")

        monkeypatch.setattr(opencode, "run_cli", fake_run_cli)
        delete_session(config_factory(), "s1", None)
        assert captured["cwd"] == config_factory().data_dir

    def test_non_dir_falls_back(self, config_factory, tmp_path, monkeypatch):
        captured = {}

        def fake_run_cli(_config, args, *, cwd=None, timeout=None):
            captured["cwd"] = cwd
            return CliResult([], 0, "", "")

        monkeypatch.setattr(opencode, "run_cli", fake_run_cli)
        cfg = config_factory()
        delete_session(cfg, "s1", str(tmp_path / "missing"))
        assert captured["cwd"] == cfg.data_dir

@pytest.mark.parametrize("returncode,expected", [(0, True), (1, False)])
def test_cli_result_ok(returncode, expected):
    assert CliResult([], returncode, "", "").ok is expected

def test_resolve_bin_returns_path_type(tmp_path):
    assert isinstance(str(Path(tmp_path)), str)
