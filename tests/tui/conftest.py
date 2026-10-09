"""Shared fixtures for the headless Textual TUI tests."""

from __future__ import annotations
import asyncio
import pytest
import ocdu.tui.app as tui_app
import ocdu.tui.screens.base as tui_base
import ocdu.tui.screens.browse as tui_browse
import ocdu.tui.screens.detail as tui_detail
import ocdu.tui.screens.sessions as tui_sessions
import ocdu.tui.screens.theme as tui_theme
from ocdu.safety import SafetyStatus
from tests.factories import EventFactory, MessageFactory, PartFactory, ProjectFactory, SessionFactory

def _safe_probe(*_a, **_k) -> SafetyStatus:
    return SafetyStatus(db_in_use=False, opencode_processes=[])

def _noop_save(*_a, **_k) -> None:
    return None

@pytest.fixture(autouse=True)
def _isolate_tui(monkeypatch):
    """Keep TUI tests off the real filesystem and OpenCode processes."""
    monkeypatch.setattr(tui_browse, "probe", _safe_probe)
    monkeypatch.setattr(tui_base, "probe", _safe_probe)
    monkeypatch.setattr(tui_app, "save_ui_overrides", _noop_save)
    monkeypatch.setattr(tui_theme, "save_ui_overrides", _noop_save)
    monkeypatch.setattr(tui_sessions, "opencode_processes", lambda: [])
    monkeypatch.setattr(tui_detail, "opencode_processes", lambda: [])

@pytest.fixture
def run_tui():
    def _run(coro_factory):
        return asyncio.run(coro_factory())

    return _run

@pytest.fixture
def tui_env(make_db, config_factory, apply_config):
    def _make(rows: dict | None = None):
        default_rows = {
            "project": [ProjectFactory(id="prj0")],
            "session": [
                SessionFactory(id="ses1", project_id="prj0", title="Hello", directory="/work/dir")
            ],
            "message": [
                MessageFactory(id="m1", session_id="ses1", data='{"role": "user", "time": {"created": 1}}')
            ],
            "part": [
                PartFactory(id="p1", message_id="m1", session_id="ses1", data='{"type": "text", "text": "hello"}')
            ],
            "event": [EventFactory(aggregate_id="ses1", data="abcd")],
        }
        db_path = make_db(default_rows if rows is None else rows)
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)
        apply_config(cfg)
        return cfg, db_path

    return _make
