"""Tests for ocdu.model dataclasses."""

from __future__ import annotations
from pathlib import Path
from ocdu.model import (
    CATEGORY_BACKUP,
    CATEGORY_INFO,
    CATEGORY_LOCKED,
    CATEGORY_MANAGED,
    CATEGORY_ORDER,
    BackupResult,
    DirectorySummary,
    OrphanReport,
    PruneResult,
    RootEntry,
    ScanReport,
    SessionSize,
    VacuumResult,
)

def _session_size(**overrides) -> SessionSize:
    base = {
        "session_id": "s1",
        "title": "t",
        "directory": "/d",
        "is_root": True,
        "message_count": 0,
        "child_count": 0,
        "event_bytes": 0,
        "message_bytes": 0,
        "part_bytes": 0,
        "session_message_bytes": 0,
        "todo_bytes": 0,
        "time_updated": 0,
    }
    base.update(overrides)
    return SessionSize(**base)

class TestRootEntry:

    def test_all_paths_includes_companions(self):
        entry = RootEntry(
            key="database",
            label="Database",
            path=Path("/db/opencode.db"),
            category=CATEGORY_MANAGED,
            companions=[Path("/db/opencode.db-wal"), Path("/db/opencode.db-shm")],
        )
        assert entry.all_paths == [
            Path("/db/opencode.db"),
            Path("/db/opencode.db-wal"),
            Path("/db/opencode.db-shm"),
        ]

    def test_all_paths_without_companions(self):
        entry = RootEntry(key="k", label="l", path=Path("/p"), category=CATEGORY_INFO)
        assert entry.all_paths == [Path("/p")]

class TestScanReport:

    def test_total_bytes(self):
        report = ScanReport(entries=[
            RootEntry(key="a", label="a", path=Path("/a"), category=CATEGORY_MANAGED, size_bytes=10),
            RootEntry(key="b", label="b", path=Path("/b"), category=CATEGORY_INFO, size_bytes=5),
        ])
        assert report.total_bytes == 15

    def test_get_found_and_missing(self):
        entry = RootEntry(key="a", label="a", path=Path("/a"), category=CATEGORY_MANAGED)
        report = ScanReport(entries=[entry])
        assert report.get("a") is entry
        assert report.get("nope") is None

class TestSessionSize:

    def test_total_bytes(self):
        session = _session_size(
            event_bytes=1, message_bytes=2, part_bytes=3, session_message_bytes=4, todo_bytes=5
        )
        assert session.total_bytes == 15

class TestOrphanReport:

    def test_derived_sizes(self):
        report = OrphanReport(orphan_event_bytes=10, orphan_session_diff_bytes=7)
        assert report.event_bytes == 10
        assert report.session_diff_bytes == 7
        assert report.total_bytes == 17

class TestPruneResult:

    def test_freed_bytes(self):
        result = PruneResult(orphan_event_bytes=4, session_diff_bytes=6)
        assert result.freed_bytes == 10

class TestVacuumResult:

    def test_saved_bytes_positive(self):
        assert VacuumResult(before_bytes=100, after_bytes=40).saved_bytes == 60

    def test_saved_bytes_never_negative(self):
        assert VacuumResult(before_bytes=40, after_bytes=100).saved_bytes == 0

class TestCategoryConstants:

    def test_order_and_values(self):
        assert CATEGORY_ORDER == (
            CATEGORY_MANAGED,
            CATEGORY_INFO,
            CATEGORY_LOCKED,
            CATEGORY_BACKUP,
        )

class TestOtherDataclasses:

    def test_backup_result_defaults(self):
        result = BackupResult(path=Path("/a.zip"), db_bytes=1, total_bytes=2, extra_files=0)
        assert result.removed_old == []

    def test_directory_summary_fields(self):
        summary = DirectorySummary(
            directory="/d", size_bytes=1, session_count=2, root_count=1, last_updated=3, exists=True
        )
        assert summary.session_count == 2
