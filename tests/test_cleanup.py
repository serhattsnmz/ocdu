"""Tests for ocdu.cleanup (prune, vacuum, checkpoint, log cleanup)."""

from __future__ import annotations
from pathlib import Path
import pytest
import ocdu.cleanup as cleanup_module
from ocdu.cleanup import (
    _connect_rw,
    _db_total,
    checkpoint,
    clean_logs,
    delete_orphan_events,
    delete_orphan_session_diff,
    integrity_check,
    prune,
    vacuum,
    vacuum_dry_run,
)
from ocdu.db import Database
from ocdu.model import VacuumResult
from tests.factories import EventFactory, ProjectFactory, SessionFactory
from tests.helpers import age_file

def blen(text: str) -> int:
    return len(text.encode("utf-8"))

def _orphan_rows() -> dict:
    return {
        "project": [ProjectFactory(id="prj0")],
        "session": [SessionFactory(id="ses1", project_id="prj0")],
        "event_sequence": [
            {"aggregate_id": "ses1", "seq": 1},
            {"aggregate_id": "ghost", "seq": 1},
        ],
        "event": [
            EventFactory(id="e1", aggregate_id="ses1", data="aa"),
            EventFactory(id="e2", aggregate_id="ghost", data="bbbb"),
        ],
    }

def _config(config_factory, db_path):
    return config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)

class TestHelpers:

    def test_db_total_sums_companions(self, tmp_path, config_factory):
        base = tmp_path / "opencode.db"
        base.write_bytes(b"x" * 10)
        Path(str(base) + "-wal").write_bytes(b"y" * 4)
        Path(str(base) + "-shm").write_bytes(b"z" * 2)
        assert _db_total(_config(config_factory, base)) == 16

    def test_connect_rw_missing(self, config_factory):
        with pytest.raises(FileNotFoundError):
            _connect_rw(config_factory())

class TestDeleteOrphanEvents:

    def test_removes_orphans_only(self, make_db, config_factory):
        db_path = make_db(_orphan_rows())
        count, freed = delete_orphan_events(_config(config_factory, db_path))
        assert count == 1
        assert freed == blen("bbbb")
        db = Database(db_path)
        with db.open() as connection:
            assert db.session_ids(connection) == {"ses1"}
            assert db.orphan_event_bytes(connection) == (0, 0)

    def test_no_orphans(self, make_db, config_factory):
        rows = {"project": [ProjectFactory(id="prj0")], "session": [SessionFactory(id="ses1", project_id="prj0")]}
        db_path = make_db(rows)
        assert delete_orphan_events(_config(config_factory, db_path)) == (0, 0)

class TestDeleteOrphanSessionDiff:

    def test_deletes_listed_files(self, tmp_path):
        first = tmp_path / "a.json"
        second = tmp_path / "b.json"
        first.write_text("aa", encoding="utf-8")
        second.write_text("bbb", encoding="utf-8")
        count, freed = delete_orphan_session_diff([first, tmp_path / "missing.json", second])
        assert count == 2
        assert freed == 5
        assert not first.exists() and not second.exists()

class TestPrune:

    def test_prunes_both_by_default(self, make_db, config_factory, tmp_path):
        db_path = make_db(_orphan_rows())
        cfg = _config(config_factory, db_path)
        diff_dir = cfg.data_dir / "storage" / "session_diff"
        diff_dir.mkdir(parents=True)
        (diff_dir / "ghost.json").write_text("yyyyy", encoding="utf-8")
        result = prune(cfg)
        assert result.orphan_event_sequences == 1
        assert result.session_diff_files == 1
        assert not (diff_dir / "ghost.json").exists()

    def test_skip_events(self, make_db, config_factory):
        db_path = make_db(_orphan_rows())
        cfg = _config(config_factory, db_path)
        result = prune(cfg, do_events=False)
        assert result.orphan_event_sequences == 0
        db = Database(db_path)
        with db.open() as connection:
            assert db.orphan_event_bytes(connection)[0] == 1

    def test_backup_called_with_diff_files(self, make_db, config_factory, monkeypatch):
        db_path = make_db(_orphan_rows())
        cfg = _config(config_factory, db_path)
        diff_dir = cfg.data_dir / "storage" / "session_diff"
        diff_dir.mkdir(parents=True)
        ghost = diff_dir / "ghost.json"
        ghost.write_text("y", encoding="utf-8")
        captured = {}

        def _fake_backup(_cfg, extra_files=None):
            captured["extra"] = extra_files

        monkeypatch.setattr(cleanup_module, "create_backup", _fake_backup)
        prune(cfg, backup=True)
        assert captured["extra"] == [ghost]

class TestVacuum:

    def test_vacuum_keeps_database_valid(self, make_db, config_factory):
        db_path = make_db(_orphan_rows())
        cfg = _config(config_factory, db_path)
        result = vacuum(cfg)
        assert isinstance(result, VacuumResult)
        assert result.before_bytes > 0
        assert integrity_check(cfg) == "ok"

    def test_dry_run(self, make_db, config_factory):
        db_path = make_db(_orphan_rows())
        result = vacuum_dry_run(_config(config_factory, db_path))
        assert isinstance(result, VacuumResult)
        assert result.before_bytes > 0
        assert result.after_bytes <= result.before_bytes

    def test_checkpoint(self, make_db, config_factory):
        db_path = make_db(_orphan_rows())
        assert isinstance(checkpoint(_config(config_factory, db_path)), VacuumResult)

class TestIntegrityAndCheckpoint:

    def test_integrity_check_ok(self, make_db, config_factory):
        db_path = make_db(_orphan_rows())
        assert integrity_check(_config(config_factory, db_path)) == "ok"

class TestCleanLogs:

    def _setup(self, config_factory, tmp_path, **extra):
        cfg = config_factory(**extra)
        log_dir = cfg.data_dir / "log"
        log_dir.mkdir(parents=True)
        old = log_dir / "old.log"
        old.write_bytes(b"x" * 10)
        age_file(old, 10)
        fresh = log_dir / "fresh.log"
        fresh.write_bytes(b"y" * 3)
        (log_dir / "subdir").mkdir()
        return cfg, old, fresh

    def test_removes_old_keeps_fresh(self, config_factory, tmp_path):
        cfg, old, fresh = self._setup(config_factory, tmp_path, LOG_RETENTION_DAYS="5")
        count, freed = clean_logs(cfg)
        assert count == 1
        assert freed == 10
        assert not old.exists()
        assert fresh.exists()

    def test_dry_run_keeps_files(self, config_factory, tmp_path):
        cfg, old, _fresh = self._setup(config_factory, tmp_path, LOG_RETENTION_DAYS="5")
        count, _freed = clean_logs(cfg, dry_run=True)
        assert count == 1
        assert old.exists()

    def test_missing_log_dir(self, config_factory, tmp_path):
        cfg = config_factory()
        assert clean_logs(cfg) == (0, 0)

    def test_explicit_zero_days_removes_all(self, config_factory, tmp_path):
        cfg, old, fresh = self._setup(config_factory, tmp_path, LOG_RETENTION_DAYS="30")
        count, _freed = clean_logs(cfg, 0)
        assert count == 2
        assert not old.exists() and not fresh.exists()

    def test_negative_days_treated_as_zero(self, config_factory, tmp_path):
        cfg, _old, fresh = self._setup(config_factory, tmp_path, LOG_RETENTION_DAYS="30")
        count, _freed = clean_logs(cfg, -5)
        assert count == 2
        assert not fresh.exists()

    def test_unlink_error_is_skipped(self, config_factory, tmp_path, monkeypatch):
        cfg, old, _fresh = self._setup(config_factory, tmp_path, LOG_RETENTION_DAYS="5")

        def _failing_unlink(self, *args, **kwargs):
            raise OSError("locked")

        monkeypatch.setattr(Path, "unlink", _failing_unlink)
        assert clean_logs(cfg, 0) == (0, 0)
        assert old.exists()

