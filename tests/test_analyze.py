"""Tests for ocdu.analyze (footprint scanning, sizing, orphan detection)."""

from __future__ import annotations
from pathlib import Path
from ocdu.analyze import directory_summaries, orphan_report, scan_root, scan_roots, session_sizes
from ocdu.db import Database
from ocdu.model import CATEGORY_INFO, RootEntry, ScanReport
from tests.factories import (
    EventFactory,
    MessageFactory,
    PartFactory,
    ProjectFactory,
    SessionFactory,
    SessionMessageFactory,
    TodoFactory,
)

def _rows(tmp_path) -> dict:
    proj_a = str(tmp_path / "projA")
    proj_b = str(tmp_path / "projB")
    return {
        "project": [ProjectFactory(id="prj0")],
        "session": [
            SessionFactory(id="ses1", project_id="prj0", directory=proj_a, time_updated=100),
            SessionFactory(
                id="ses2", project_id="prj0", parent_id="ses1", directory=proj_a,
                time_updated=200, tokens_input=1, cost=0.5,
            ),
            SessionFactory(
                id="ses3", project_id="prj0", parent_id="ses2", directory=proj_a, time_updated=300
            ),
            SessionFactory(id="ses4", project_id="prj0", directory=proj_b, time_updated=50),
        ],
        "message": [
            MessageFactory(id="m1", session_id="ses1", data="aaaa"),
            MessageFactory(id="m2", session_id="ses2", data="bb"),
            MessageFactory(id="m3", session_id="ses3", data="c"),
            MessageFactory(id="m4", session_id="ses4", data="q"),
        ],
        "part": [PartFactory(id="p1", message_id="m1", session_id="ses1", data="ppp")],
        "session_message": [SessionMessageFactory(id="sm1", session_id="ses1", data="zzz")],
        "todo": [TodoFactory(session_id="ses1", content="tt")],
        "event": [EventFactory(aggregate_id="ses1", data="eeee")],
    }

class TestScanRoot:

    def test_missing_path(self, tmp_path):
        entry = RootEntry(key="k", label="l", path=tmp_path / "nope", category=CATEGORY_INFO)
        scan_root(entry)
        assert entry.exists is False
        assert entry.size_bytes == 0
        assert entry.file_count == 0

    def test_directory(self, tmp_path):
        (tmp_path / "a.bin").write_bytes(b"x" * 5)
        entry = RootEntry(key="k", label="l", path=tmp_path, category=CATEGORY_INFO)
        scan_root(entry)
        assert entry.exists is True
        assert (entry.size_bytes, entry.file_count) == (5, 1)

    def test_file_with_companions(self, tmp_path):
        db = tmp_path / "opencode.db"
        db.write_bytes(b"x" * 10)
        wal = Path(str(db) + "-wal")
        wal.write_bytes(b"y" * 4)
        entry = RootEntry(
            key="database",
            label="db",
            path=db,
            category=CATEGORY_INFO,
            companions=[wal, Path(str(db) + "-shm")],
        )
        scan_root(entry)
        assert entry.exists is True
        assert entry.size_bytes == 14
        assert entry.file_count == 2

class TestScanRoots:

    def test_preserves_order_and_calls_callback(self, tmp_path):
        entries = [
            RootEntry(key=f"k{i}", label=str(i), path=tmp_path / f"d{i}", category=CATEGORY_INFO)
            for i in range(3)
        ]
        seen: list[str] = []
        report = scan_roots(entries, on_entry=lambda entry: seen.append(entry.key))
        assert isinstance(report, ScanReport)
        assert [entry.key for entry in report.entries] == ["k0", "k1", "k2"]
        assert sorted(seen) == ["k0", "k1", "k2"]

    def test_empty_list(self):
        report = scan_roots([])
        assert report.entries == []

class TestSessionSizes:

    def test_roots_only_aggregates_descendants(self, make_db, tmp_path):
        db = Database(make_db(_rows(tmp_path)))
        with db.open() as connection:
            sessions = {s.session_id: s for s in session_sizes(db, connection, roots_only=True)}
        assert set(sessions) == {"ses1", "ses4"}
        root = sessions["ses1"]
        assert root.total_bytes == 19
        assert root.message_count == 3
        assert root.child_count == 2
        assert root.tokens_input == 1
        assert root.cost == 0.5
        assert sessions["ses4"].total_bytes == 1

    def test_flat_lists_every_session(self, make_db, tmp_path):
        db = Database(make_db(_rows(tmp_path)))
        with db.open() as connection:
            sessions = {s.session_id: s for s in session_sizes(db, connection, roots_only=False)}
        assert set(sessions) == {"ses1", "ses2", "ses3", "ses4"}
        assert sessions["ses1"].child_count == 1
        assert sessions["ses2"].child_count == 1
        assert sessions["ses3"].child_count == 0
        assert sessions["ses1"].total_bytes == 16

class TestDirectorySummaries:

    def test_counts_and_sorting(self, make_db, tmp_path):
        rows = _rows(tmp_path)
        (tmp_path / "projA").mkdir()
        db = Database(make_db(rows))
        with db.open() as connection:
            summaries = directory_summaries(db, connection)
        by_dir = {summary.directory: summary for summary in summaries}
        proj_a = by_dir[str(tmp_path / "projA")]
        assert proj_a.session_count == 3
        assert proj_a.root_count == 1
        assert proj_a.size_bytes == 19
        assert proj_a.last_updated == 300
        assert proj_a.exists is True
        proj_b = by_dir[str(tmp_path / "projB")]
        assert proj_b.exists is False
        assert summaries[0].size_bytes >= summaries[-1].size_bytes

class TestOrphanReport:

    def test_events_and_diff_files(self, make_db, config_factory, tmp_path):
        rows = _rows(tmp_path)
        rows["event_sequence"] = [
            {"aggregate_id": "ses1", "seq": 1},
            {"aggregate_id": "ghost", "seq": 1},
        ]
        rows["event"] = [
            EventFactory(id="e1", aggregate_id="ses1", data="aa"),
            EventFactory(id="e2", aggregate_id="ghost", data="bbbb"),
        ]
        diff_dir = tmp_path / "data" / "storage" / "session_diff"
        diff_dir.mkdir(parents=True)
        (diff_dir / "ses1.json").write_text("x" * 3, encoding="utf-8")
        (diff_dir / "ghost.json").write_text("y" * 5, encoding="utf-8")
        (diff_dir / "notes.txt").write_text("z", encoding="utf-8")
        (diff_dir / "nested").mkdir()
        (diff_dir / "nested" / "deep.json").write_text("q", encoding="utf-8")
        cfg = config_factory(OPENCODE_DATA_DIR=str(tmp_path / "data"))
        db = Database(make_db(rows))
        with db.open() as connection:
            report = orphan_report(db, connection, cfg)
        assert report.orphan_event_sequences == 1
        assert report.orphan_event_bytes == 4
        assert [path.name for path in report.orphan_session_diff_files] == ["ghost.json"]
        assert report.orphan_session_diff_bytes == 5

    def test_missing_diff_dir(self, make_db, config_factory, tmp_path):
        db = Database(make_db(_rows(tmp_path)))
        cfg = config_factory(OPENCODE_DATA_DIR=str(tmp_path / "data"))
        with db.open() as connection:
            report = orphan_report(db, connection, cfg)
        assert report.orphan_session_diff_files == []
