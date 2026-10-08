"""Tests for ocdu.safety (lock detection and process probing)."""

from __future__ import annotations
import sqlite3
import subprocess
import sys
from types import SimpleNamespace
import ocdu.safety as safety
from ocdu.safety import SafetyStatus, database_in_use, opencode_processes, probe

class TestSafetyStatus:

    def test_safe_when_clean(self):
        assert SafetyStatus(db_in_use=False, opencode_processes=[]).safe_for_exclusive is True

    def test_unsafe_when_db_in_use(self):
        assert SafetyStatus(db_in_use=True, opencode_processes=[]).safe_for_exclusive is False

    def test_unsafe_when_process_running(self):
        assert SafetyStatus(db_in_use=False, opencode_processes=["opencode"]).safe_for_exclusive is False

    def test_describe_clean(self):
        assert SafetyStatus(False, []).describe() == "no OpenCode instance detected"

    def test_describe_db_only(self):
        assert "locked" in SafetyStatus(True, []).describe()

    def test_describe_processes_only(self):
        text = SafetyStatus(False, ["opencode.exe 1", "opencode.exe 2"]).describe()
        assert "OpenCode process(es) running" in text
        assert "opencode.exe 1" in text

    def test_describe_both(self):
        text = SafetyStatus(True, ["opencode.exe 1"]).describe()
        assert "locked" in text
        assert "opencode.exe 1" in text

class TestDatabaseInUse:

    def test_missing_database(self, config_factory):
        assert database_in_use(config_factory()) is False

    def test_free_database(self, make_db, config_factory):
        db_path = make_db({"session": []})
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)
        assert database_in_use(cfg) is False

    def test_locked_database(self, make_db, config_factory):
        db_path = make_db({})
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)
        holder = sqlite3.connect(str(db_path))
        holder.execute("BEGIN IMMEDIATE")
        try:
            assert database_in_use(cfg) is True
        finally:
            holder.execute("ROLLBACK")
            holder.close()

    def test_connect_error_reports_in_use(self, make_db, config_factory, monkeypatch):
        db_path = make_db({})
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)

        def _boom(*_args, **_kwargs):
            raise sqlite3.Error("cannot open")

        monkeypatch.setattr(safety.sqlite3, "connect", _boom)
        assert database_in_use(cfg) is True


class TestOpencodeProcesses:

    def test_windows_branch(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        output = "opencode.exe  1234  Console  1  10.000 K\nother.exe  5  Console\n"
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=output))
        result = opencode_processes()
        assert result == ["opencode.exe  1234  Console  1  10.000 K"]

    def test_posix_branch(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr(subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="111 opencode\n\n222 other\n"))
        assert opencode_processes() == ["111 opencode", "222 other"]

    def test_errors_return_empty(self, monkeypatch):
        def fake_run(*_args, **_kwargs):
            raise OSError("no tasklist")

        monkeypatch.setattr(subprocess, "run", fake_run)
        assert opencode_processes() == []

class TestProbe:

    def test_combines_probes(self, monkeypatch):
        monkeypatch.setattr(safety, "database_in_use", lambda _cfg: True)
        monkeypatch.setattr(safety, "opencode_processes", lambda: ["opencode"])
        status = probe(object())
        assert status.db_in_use is True
        assert status.opencode_processes == ["opencode"]
