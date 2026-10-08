"""Tests for ocdu.session_ops (session rename)."""

from __future__ import annotations
import sqlite3
from ocdu.session_ops import set_title
from tests.factories import ProjectFactory, SessionFactory

def _config(config_factory, db_path):
    return config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)

def _rows() -> dict:
    return {
        "project": [ProjectFactory(id="prj0")],
        "session": [SessionFactory(id="ses1", project_id="prj0", title="old", time_updated=1)],
    }

class TestSetTitle:

    def test_renames_existing_session(self, make_db, config_factory):
        db_path = make_db(_rows())
        assert set_title(_config(config_factory, db_path), "ses1", "New title") is True
        connection = sqlite3.connect(db_path)
        try:
            title, updated = connection.execute(
                "SELECT title, time_updated FROM session WHERE id = 'ses1'"
            ).fetchone()
        finally:
            connection.close()
        assert title == "New title"
        assert updated > 1

    def test_missing_session_returns_false(self, make_db, config_factory):
        db_path = make_db(_rows())
        assert set_title(_config(config_factory, db_path), "ghost", "x") is False
