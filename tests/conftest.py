"""Shared fixtures for the ocdu test suite.

Every test runs against a throwaway synthetic database (or no database at all);
the real OpenCode data is never touched. Subprocesses are blocked by default so
tests must explicitly monkeypatch any external command they exercise.
"""

from __future__ import annotations
import itertools
import sqlite3
import subprocess
from pathlib import Path
import pytest
import ocdu.analyze as analyze_module
import ocdu.config as config_module
import ocdu.db as db_module
import ocdu.paths as paths_module
import ocdu.state as state_module
import ocdu.__main__ as main_module
from ocdu.config import _DEFAULTS, Config, _expand_references
from ocdu.tui import app as tui_app
from ocdu.tui.screens import base as tui_base
from ocdu.tui.screens import browse as tui_browse
from ocdu.tui.screens import dashboard as tui_dashboard
from ocdu.tui.screens import detail as tui_detail
from ocdu.tui.screens import sessions as tui_sessions
from ocdu.tui.screens import stats as tui_stats

SCHEMA = """
CREATE TABLE project (
    id TEXT PRIMARY KEY,
    worktree TEXT NOT NULL,
    vcs TEXT,
    name TEXT,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    sandboxes TEXT NOT NULL
);
CREATE TABLE session (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    parent_id TEXT,
    slug TEXT NOT NULL,
    directory TEXT NOT NULL,
    title TEXT NOT NULL,
    version TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    path TEXT,
    agent TEXT,
    model TEXT,
    cost REAL DEFAULT 0 NOT NULL,
    tokens_input INTEGER DEFAULT 0 NOT NULL,
    tokens_output INTEGER DEFAULT 0 NOT NULL,
    tokens_reasoning INTEGER DEFAULT 0 NOT NULL,
    FOREIGN KEY (project_id) REFERENCES project(id) ON DELETE CASCADE
);
CREATE TABLE message (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE
);
CREATE TABLE part (
    id TEXT PRIMARY KEY,
    message_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data TEXT NOT NULL,
    FOREIGN KEY (message_id) REFERENCES message(id) ON DELETE CASCADE
);
CREATE TABLE session_message (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    type TEXT NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    data TEXT NOT NULL,
    seq INTEGER NOT NULL,
    FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE
);
CREATE TABLE todo (
    session_id TEXT NOT NULL,
    content TEXT NOT NULL,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    position INTEGER NOT NULL,
    time_created INTEGER NOT NULL,
    time_updated INTEGER NOT NULL,
    PRIMARY KEY (session_id, position),
    FOREIGN KEY (session_id) REFERENCES session(id) ON DELETE CASCADE
);
CREATE TABLE event_sequence (
    aggregate_id TEXT PRIMARY KEY,
    seq INTEGER NOT NULL,
    owner_id TEXT
);
CREATE TABLE event (
    id TEXT PRIMARY KEY,
    aggregate_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    data TEXT NOT NULL,
    FOREIGN KEY (aggregate_id) REFERENCES event_sequence(aggregate_id) ON DELETE CASCADE
);
"""

_CONFIG_TARGETS = (
    (config_module, "config"),
    (main_module, "config"),
    (paths_module, "default_config"),
    (analyze_module, "default_config"),
    (state_module, "default_config"),
    (tui_app, "config"),
    (tui_base, "config"),
    (tui_browse, "config"),
    (tui_sessions, "config"),
    (tui_detail, "config"),
    (tui_dashboard, "config"),
    (tui_stats, "config"),
)

@pytest.fixture(autouse=True)
def _guard_subprocess(monkeypatch):
    """Fail loudly if a test reaches a real external command unmocked."""

    def _blocked(*_args, **_kwargs):
        raise AssertionError("unexpected subprocess.run call; monkeypatch it in the test")

    monkeypatch.setattr(subprocess, "run", _blocked)

@pytest.fixture(autouse=True)
def _clear_size_cache():
    """Keep the module-level session-size cache from leaking across tests."""
    db_module._SIZE_CACHE.clear()
    yield
    db_module._SIZE_CACHE.clear()

@pytest.fixture
def make_db(tmp_path):
    """Return a factory that writes a fresh schema-only test database."""
    names = itertools.count()

    def _make(rows: dict[str, list[dict]] | None = None) -> Path:
        path = tmp_path / f"ocdu-test-{next(names)}.db"
        connection = sqlite3.connect(path)
        try:
            connection.executescript(SCHEMA)
            for table, table_rows in (rows or {}).items():
                for row in table_rows:
                    columns = ", ".join(row)
                    placeholders = ", ".join("?" for _ in row)
                    connection.execute(
                        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
                        tuple(row.values()),
                    )
            connection.commit()
        finally:
            connection.close()
        return path

    return _make

@pytest.fixture
def config_factory(tmp_path):
    """Return a factory building a :class:`Config` rooted inside ``tmp_path``."""

    def _make(**overrides) -> Config:
        base = {
            "OPENCODE_DATA_DIR": str(tmp_path / "data"),
            "OPENCODE_STATE_DIR": str(tmp_path / "state"),
            "OPENCODE_CACHE_DIR": str(tmp_path / "cache"),
            "OPENCODE_CONFIG_DIR": str(tmp_path / "config"),
        }
        base.update({key: str(value) for key, value in overrides.items()})
        merged = dict(_DEFAULTS)
        merged.update(base)
        return Config(_expand_references(merged))

    return _make

@pytest.fixture
def apply_config(monkeypatch):
    """Return a helper that installs ``cfg`` as the global config everywhere."""

    def _apply(cfg: Config) -> Config:
        for module, attr in _CONFIG_TARGETS:
            monkeypatch.setattr(module, attr, cfg, raising=False)
        return cfg

    return _apply
