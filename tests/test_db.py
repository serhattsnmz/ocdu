"""Tests for ocdu.db (read-only SQLite access and size queries)."""

from __future__ import annotations
import sqlite3
import pytest
from ocdu.db import Database, _database_state, _readonly_uri
from tests.factories import (
    EventFactory,
    MessageFactory,
    PartFactory,
    ProjectFactory,
    SessionFactory,
    SessionMessageFactory,
    TodoFactory,
)

def blen(text: str) -> int:
    return len(text.encode("utf-8"))

def _base_rows() -> dict:
    return {
        "project": [ProjectFactory(id="prj0")],
        "session": [
            SessionFactory(id="ses1", project_id="prj0", directory="/d"),
            SessionFactory(id="ses2", project_id="prj0", directory="/d"),
        ],
    }

class TestReadonlyUri:

    def test_has_readonly_mode(self, tmp_path):
        uri = _readonly_uri(tmp_path / "x.db")
        assert uri.startswith("file:")
        assert uri.endswith("?mode=ro")

class TestConnection:

    def test_exists(self, make_db, tmp_path):
        assert Database(make_db()).exists() is True
        assert Database(tmp_path / "missing.db").exists() is False

    def test_row_factory_is_row(self, make_db):
        db = Database(make_db(_base_rows()))
        with db.open() as connection:
            row = connection.execute("SELECT id FROM session").fetchone()
            assert row["id"]


    def test_readonly_connection_rejects_writes(self, make_db):
        db = Database(make_db(_base_rows()))
        with db.open() as connection, pytest.raises(sqlite3.OperationalError):
            connection.execute(
                "INSERT INTO session "
                "(id, project_id, slug, directory, title, version, time_created, time_updated) "
                "VALUES ('x','prj0','s','/','t','1',0,0)"
            )

    def test_connect_missing_file_raises(self, tmp_path):
        with pytest.raises(sqlite3.OperationalError):
            Database(tmp_path / "missing.db").connect()

class TestPragmas:

    def test_page_size_and_freelist(self, make_db):
        db = Database(make_db(_base_rows()))
        with db.open() as connection:
            assert db.page_size(connection) > 0
            assert db.freelist_count(connection) >= 0

    def test_integrity_check_ok(self, make_db):
        db = Database(make_db(_base_rows()))
        with db.open() as connection:
            assert db.integrity_check(connection) == "ok"

class TestSizeBySession:

    def test_payload_bytes_per_table(self, make_db):
        rows = _base_rows()
        rows["event"] = [EventFactory(aggregate_id="ses1", data='{"a": 1}')]
        rows["message"] = [MessageFactory(id="m1", session_id="ses1", data="hello")]
        rows["part"] = [PartFactory(id="p1", message_id="m1", session_id="ses1", data="world")]
        rows["session_message"] = [SessionMessageFactory(id="sm1", session_id="ses1", data="xy")]
        rows["todo"] = [TodoFactory(session_id="ses1", content="task")]
        db = Database(make_db(rows))
        with db.open() as connection:
            sizes = db.size_by_session(connection)
        assert sizes["ses1"]["event"] == blen('{"a": 1}')
        assert sizes["ses1"]["message"] == blen("hello")
        assert sizes["ses1"]["part"] == blen("world")
        assert sizes["ses1"]["session_message"] == blen("xy")
        assert sizes["ses1"]["todo"] == blen("task")

    def test_multibyte_uses_utf8_length(self, make_db):
        rows = _base_rows()
        rows["message"] = [MessageFactory(id="m1", session_id="ses1", data="üü")]
        db = Database(make_db(rows))
        with db.open() as connection:
            sizes = db.size_by_session(connection)
        assert sizes["ses1"]["message"] == 4

    def test_cache_returns_same_object(self, make_db):
        db = Database(make_db(_base_rows()))
        with db.open() as connection:
            assert db.size_by_session(connection) is db.size_by_session(connection)

    def test_cache_invalidated_when_file_changes(self, make_db):
        rows = _base_rows()
        rows["event"] = [EventFactory(aggregate_id="ses1", data="aaa")]
        path = make_db(rows)
        db = Database(path)
        with db.open() as connection:
            first = db.size_by_session(connection)["ses1"]["event"]
        connection = sqlite3.connect(path)
        connection.execute(
            "INSERT INTO event (id, aggregate_id, seq, type, data) VALUES ('e2','ses1',2,'x',?)",
            ("z" * 200_000,),
        )
        connection.commit()
        connection.close()
        with db.open() as connection:
            second = db.size_by_session(connection)["ses1"]["event"]
        assert second > first

    def test_change_counter_changes_on_same_size_write(self, make_db):
        rows = _base_rows()
        rows["event"] = [EventFactory(id="e1", aggregate_id="ses1", data="aaa")]
        path = make_db(rows)
        before = _database_state(path)
        connection = sqlite3.connect(path)
        connection.execute("UPDATE event SET data = 'bbb' WHERE id = 'e1'")
        connection.commit()
        connection.close()
        after = _database_state(path)
        assert after[0][2] != before[0][2]

class TestSizeByDirectory:

    def test_groups_by_directory_and_skips_payloadless_sessions(self, make_db):
        rows = _base_rows()
        rows["event"] = [EventFactory(aggregate_id="ses1", data="abcd")]
        db = Database(make_db(rows))
        with db.open() as connection:
            totals = db.size_by_directory(connection)
        assert totals == {"/d": blen("abcd")}

class TestOrphanEventBytes:

    def test_reports_orphans(self, make_db):
        rows = _base_rows()
        rows["event_sequence"] = [
            {"aggregate_id": "ses1", "seq": 1},
            {"aggregate_id": "ghost", "seq": 1},
        ]
        rows["event"] = [
            EventFactory(id="e1", aggregate_id="ses1", data="aa"),
            EventFactory(id="e2", aggregate_id="ghost", data="bbbb"),
        ]
        db = Database(make_db(rows))
        with db.open() as connection:
            count, total = db.orphan_event_bytes(connection)
        assert count == 1
        assert total == blen("bbbb")

    def test_orphan_sequence_without_events_counts_with_zero_bytes(self, make_db):
        rows = _base_rows()
        rows["event_sequence"] = [{"aggregate_id": "ghost", "seq": 1}]
        db = Database(make_db(rows))
        with db.open() as connection:
            count, total = db.orphan_event_bytes(connection)
        assert count == 1
        assert total == 0

    def test_no_orphans(self, make_db):
        rows = _base_rows()
        rows["event_sequence"] = [{"aggregate_id": "ses1", "seq": 1}]
        rows["event"] = [EventFactory(id="e1", aggregate_id="ses1", data="aa")]
        db = Database(make_db(rows))
        with db.open() as connection:
            assert db.orphan_event_bytes(connection) == (0, 0)

class TestMetadataQueries:

    def test_session_ids(self, make_db):
        db = Database(make_db(_base_rows()))
        with db.open() as connection:
            assert db.session_ids(connection) == {"ses1", "ses2"}

    def test_session_rows(self, make_db):
        db = Database(make_db(_base_rows()))
        with db.open() as connection:
            records = {record["id"]: record for record in db.session_rows(connection)}
        assert set(records) == {"ses1", "ses2"}
        assert set(records["ses2"]) >= {"id", "parent_id", "title", "directory", "cost"}
        assert records["ses1"]["directory"] == "/d"

    def test_message_counts(self, make_db):
        rows = _base_rows()
        rows["message"] = [
            MessageFactory(id="m1", session_id="ses1"),
            MessageFactory(id="m2", session_id="ses1"),
        ]
        db = Database(make_db(rows))
        with db.open() as connection:
            assert db.message_counts(connection) == {"ses1": 2}

    def test_root_session_ids_filters_parent_and_directory(self, make_db):
        rows = _base_rows()
        rows["session"].append(SessionFactory(id="ses3", parent_id="ses1", directory="/d"))
        db = Database(make_db(rows))
        with db.open() as connection:
            assert db.root_session_ids(connection, "/d") == ["ses1", "ses2"]
