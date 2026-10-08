"""Tests for ocdu.backup (snapshot, archive, rotation)."""

from __future__ import annotations
import os
import sqlite3
import time
import zipfile
from pathlib import Path
import pytest
import ocdu.backup as backup_module
from ocdu.backup import (
    _snapshot_database,
    backup_dir_size,
    create_backup,
    list_backups,
    rotate_backups,
)
from tests.factories import ProjectFactory, SessionFactory

def _rows() -> dict:
    return {
        "project": [ProjectFactory(id="prj0")],
        "session": [SessionFactory(id="ses1", project_id="prj0")],
    }

def _config(config_factory, db_path, **extra):
    base = {
        "OPENCODE_DATA_DIR": str(db_path.parent),
        "OPENCODE_DB_FILE": db_path.name,
        "BACKUP_DIR": str(db_path.parent / "backups"),
    }
    base.update(extra)
    return config_factory(**base)

class TestSnapshotDatabase:

    def test_produces_readable_copy(self, make_db, tmp_path):
        source = make_db(_rows())
        dest = tmp_path / "copy.db"
        size = _snapshot_database(source, dest)
        assert size > 0
        connection = sqlite3.connect(dest)
        try:
            assert connection.execute("SELECT COUNT(*) FROM session").fetchone()[0] == 1
        finally:
            connection.close()

class TestCreateBackup:

    def test_with_database(self, make_db, config_factory, tmp_path):
        db_path = make_db(_rows())
        result = create_backup(_config(config_factory, db_path))
        assert result.path.exists()
        assert result.path.name.startswith("ocdu-backup-")
        assert result.db_bytes > 0
        assert result.total_bytes > 0
        with zipfile.ZipFile(result.path) as archive:
            assert "opencode.db" in archive.namelist()

    def test_without_database(self, config_factory, tmp_path):
        cfg = config_factory(
            OPENCODE_DATA_DIR=str(tmp_path / "data"),
            OPENCODE_DB_FILE="missing.db",
            BACKUP_DIR=str(tmp_path / "backups"),
        )
        result = create_backup(cfg)
        assert result.db_bytes == 0
        with zipfile.ZipFile(result.path) as archive:
            assert archive.namelist() == []

    def test_extra_files_filtered(self, make_db, config_factory, tmp_path):
        db_path = make_db(_rows())
        good = tmp_path / "notes.txt"
        good.write_text("hi", encoding="utf-8")
        directory = tmp_path / "adir"
        directory.mkdir()
        result = create_backup(_config(config_factory, db_path), extra_files=[good, directory, tmp_path / "missing"])
        assert result.extra_files == 1
        with zipfile.ZipFile(result.path) as archive:
            assert "extra/notes.txt" in archive.namelist()

    def test_two_backups_do_not_overwrite(self, make_db, config_factory):
        db_path = make_db(_rows())
        cfg = _config(config_factory, db_path)
        create_backup(cfg)
        create_backup(cfg)
        assert len(list_backups(cfg)) == 2

    def test_archive_failure_leaves_no_partial_file(self, make_db, config_factory, monkeypatch):
        db_path = make_db(_rows())
        cfg = _config(config_factory, db_path)

        class _BoomZip:
            def __init__(self, *_a, **_k):
                raise OSError("disk full")

        monkeypatch.setattr(backup_module.zipfile, "ZipFile", _BoomZip)
        with pytest.raises(OSError):
            create_backup(cfg)
        assert list(cfg.backup_dir.glob("*.part")) == []
        assert list_backups(cfg) == []

class TestListAndRotate:

    def test_list_missing_dir(self, config_factory, tmp_path):
        cfg = config_factory(BACKUP_DIR=str(tmp_path / "absent"))
        assert list_backups(cfg) == []

    def test_list_ignores_other_files(self, config_factory, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "ocdu-backup-20240101-000000.zip").write_bytes(b"x")
        (backup_dir / "other.zip").write_bytes(b"x")
        (backup_dir / "readme.txt").write_text("x", encoding="utf-8")
        cfg = config_factory(BACKUP_DIR=str(backup_dir))
        assert [path.name for path in list_backups(cfg)] == ["ocdu-backup-20240101-000000.zip"]

    def test_rotate_keeps_newest(self, config_factory, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        base = time.time() - 1000
        for index in range(4):
            path = backup_dir / f"ocdu-backup-2024010{index}-000000.zip"
            path.write_bytes(b"x")
            os.utime(path, (base + index, base + index))
        cfg = config_factory(BACKUP_DIR=str(backup_dir), BACKUP_KEEP="2")
        removed = rotate_backups(cfg)
        assert len(removed) == 2
        assert len(list_backups(cfg)) == 2

    def test_backup_dir_size(self, config_factory, tmp_path):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        (backup_dir / "ocdu-backup-a.zip").write_bytes(b"x" * 7)
        cfg = config_factory(BACKUP_DIR=str(backup_dir))
        assert backup_dir_size(cfg) == 7

    def test_rotate_tolerates_unlink_failure(self, config_factory, tmp_path, monkeypatch):
        backup_dir = tmp_path / "backups"
        backup_dir.mkdir()
        base = time.time() - 1000
        paths = []
        for index in range(3):
            path = backup_dir / f"ocdu-backup-2024010{index}-000000.zip"
            path.write_bytes(b"x")
            os.utime(path, (base + index, base + index))
            paths.append(path)
        cfg = config_factory(BACKUP_DIR=str(backup_dir), BACKUP_KEEP="1")
        original_unlink = Path.unlink

        def _failing_unlink(self, *args, **kwargs):
            if self.name == paths[0].name:
                raise OSError("locked")
            return original_unlink(self, *args, **kwargs)

        monkeypatch.setattr(Path, "unlink", _failing_unlink)
        removed = rotate_backups(cfg)
        assert paths[0].name not in [p.name for p in removed]
        assert paths[0].exists()

