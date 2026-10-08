"""Headless tests for the ocdu Textual app and its screens."""

from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace
import pytest
from textual.actions import SkipAction
from textual.widgets import DataTable, Input, Static
from ocdu.model import (
    BackupResult,
    DirectorySummary,
    MessageTurn,
    PruneResult,
    RootEntry,
    ScanReport,
    SessionSize,
    VacuumResult,
)
from ocdu.move import MoveResult
from ocdu.opencode import CliResult
from ocdu.safety import SafetyStatus
from ocdu.tui.app import OcduApp
import ocdu.tui.app as tui_app
import ocdu.tui.screens.base as base_module
import ocdu.tui.screens.browse as browse_module
import ocdu.tui.screens.detail as detail_module
import ocdu.tui.screens.sessions as sessions_module
import ocdu.tui.screens.theme as theme_module
from ocdu.tui.screens.browse import BrowseScreen
from ocdu.tui.screens.confirm import ChoiceScreen
from ocdu.tui.screens.dashboard import DashboardScreen
from ocdu.tui.screens.detail import DetailScreen
from ocdu.tui.screens.keys import KeysScreen
from ocdu.tui.screens.prompt import TextPromptScreen
from ocdu.tui.screens.reply import ReplyScreen
from ocdu.tui.screens.sessions import SessionsScreen
from ocdu.tui.screens.stats import StatsScreen
from ocdu.tui.screens.theme import ThemePickerScreen
from ocdu.tui.loading import LoadingOverlay
from tests.factories import ProjectFactory, SessionFactory

async def settle(app, pilot) -> None:
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()

def _session_size() -> SessionSize:
    return SessionSize(
        session_id="ses1", title="Hello", directory="/work/dir", is_root=True,
        message_count=1, child_count=0, event_bytes=4, message_bytes=8,
        part_bytes=16, session_message_bytes=0, todo_bytes=0, time_updated=0,
    )

def _dir_summary() -> DirectorySummary:
    return DirectorySummary(
        directory="/work/dir", size_bytes=28, session_count=1,
        root_count=1, last_updated=0, exists=True,
    )

def _sync_workers(monkeypatch, screen) -> None:
    """Replace a screen's threaded ``run_blocking`` with a synchronous call."""
    monkeypatch.setattr(screen, "run_blocking", lambda work, on_done, **kwargs: on_done(work()))

async def _open_sessions(app, pilot) -> SessionsScreen:
    screen = SessionsScreen(_dir_summary())
    app.push_screen(screen)
    await settle(app, pilot)
    return screen


class TestAppBoot:

    def test_boots_to_browse(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                assert isinstance(app.screen, BrowseScreen)
                assert app.title == "ocdu"

        run_tui(scenario)

    def test_browse_populates_table(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                table = app.screen.query_one("#dirs", DataTable)
                assert table.row_count == 1

        run_tui(scenario)

    def test_system_commands_are_ordered(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                titles = [command.title for command in app.get_system_commands(app.screen)]
                assert titles[0] == "Theme"
                assert titles[-1] == "Quit"
                assert "Disk Stats" in titles

        run_tui(scenario)

class TestStatsAndDashboard:

    def test_dashboard_lists_every_root(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(DashboardScreen())
                await settle(app, pilot)
                table = app.screen.query_one("#roots", DataTable)
                assert table.row_count == 10

        run_tui(scenario)

    def test_stats_screen_loads(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(StatsScreen())
                await settle(app, pilot)
                assert app.screen.query_one("#models", DataTable) is not None

        run_tui(scenario)

class TestSessionsAndDetail:

    def test_sessions_screen_lists_directory(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                summary = DirectorySummary(
                    directory="/work/dir", size_bytes=28, session_count=1,
                    root_count=1, last_updated=0, exists=True,
                )
                app.push_screen(SessionsScreen(summary))
                await settle(app, pilot)
                assert app.screen.query_one("#sessions", DataTable).row_count == 1

        run_tui(scenario)

    def test_detail_screen_renders_breakdown(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(DetailScreen(_session_size()))
                await settle(app, pilot)
                detail = app.screen
                assert "TOTAL (delete removes)" in detail._build_text()

        run_tui(scenario)

    def test_reply_screen(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(ReplyScreen(MessageTurn("u1", 0, "question", "answer")))
                await settle(app, pilot)
                assert app.screen.query_one("#reply-assistant") is not None

        run_tui(scenario)

class TestModals:

    def test_confirm_escape_returns_none(self, run_tui):
        async def scenario():
            app = OcduApp()
            captured = {}
            async with app.run_test() as pilot:
                app.push_screen(
                    ChoiceScreen("Delete?", [("Yes", "yes"), ("No", "no")]),
                    lambda value: captured.update(value=value),
                )
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
            assert captured["value"] is None

        run_tui(scenario)

    def test_prompt_returns_entered_value(self, run_tui):
        async def scenario():
            app = OcduApp()
            captured = {}
            async with app.run_test() as pilot:
                app.push_screen(TextPromptScreen("Title?", initial="x"), lambda value: captured.update(value=value))
                await pilot.pause()
                app.screen.query_one("#dialog-input", Input).value = "hello"
                await pilot.press("enter")
                await pilot.pause()
            assert captured["value"] == "hello"

        run_tui(scenario)

    def test_theme_picker_escape_restores(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            captured = {}
            async with app.run_test() as pilot:
                await settle(app, pilot)
                before = app.theme
                app.push_screen(ThemePickerScreen(), lambda value: captured.update(value=value))
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert captured["value"] is None
                assert app.theme == before

        run_tui(scenario)

    def test_keys_screen_delegates_bindings(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                source = app.screen
                keys = KeysScreen(source)
                app.push_screen(keys)
                await pilot.pause()
                assert keys.active_bindings == source.active_bindings

        run_tui(scenario)


class TestSessionsScreenActions:

    def test_filter_matches_title_and_clears(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                screen._on_filter("hell")
                assert [s.session_id for s in screen.sessions] == ["ses1"]
                screen._on_filter("zzz")
                assert screen.sessions == []
                screen._on_filter(None)
                assert screen.filter_text == "zzz"

        run_tui(scenario)

    def test_toggle_sort_cycles_modes(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                assert screen.sort_index == 0
                for expected in (1, 2, 3, 0):
                    screen.action_toggle_sort()
                    assert screen.sort_index == expected

        run_tui(scenario)

    def test_toggle_mark_adds_and_removes(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                screen.action_toggle_mark()
                assert screen._marked == {"ses1"}
                screen.action_toggle_mark()
                assert screen._marked == set()

        run_tui(scenario)

    def test_marker_and_star_cells(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                assert screen._marker(True).plain == "▸"
                assert screen._marker(False).plain == " "
                assert screen._star("ses1").plain == " "

        run_tui(scenario)

    def test_restore_cursor_returns_to_saved_row(self, run_tui, tui_env):
        rows = {
            "project": [ProjectFactory(id="prj0")],
            "session": [
                SessionFactory(id="ses1", project_id="prj0", title="A", directory="/work/dir"),
                SessionFactory(id="ses2", project_id="prj0", title="B", directory="/work/dir"),
            ],
        }
        tui_env(rows)

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                table = screen.query_one("#sessions", DataTable)
                table.move_cursor(row=1)
                screen._restore_row = 0
                screen._rebuild()
                await pilot.pause()
                assert table.cursor_row == 0

        run_tui(scenario)

    def test_row_selected_opens_detail(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                screen.on_data_table_row_selected(SimpleNamespace(row_key=SimpleNamespace(value="ses1")))
                await pilot.pause()
                assert isinstance(app.screen, DetailScreen)

        run_tui(scenario)

    def test_delete_selected_unmarked_pushes_modal(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                screen.action_delete_selected()
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                assert screen._restore_row == 0
                await pilot.press("escape")
                await pilot.pause()

        run_tui(scenario)

    def test_delete_selected_marked_pushes_bulk_modal(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                screen._marked = {"ses1"}
                screen.action_delete_selected()
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                assert screen._restore_row == 0
                await pilot.press("escape")
                await pilot.pause()

        run_tui(scenario)

    def test_bulk_delete_confirmation_truncates_list(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                targets = [_session_size() for _ in range(10)]
                screen._confirm_bulk_delete(targets)
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                assert "+2 more" in app.screen.message
                await pilot.press("escape")
                await pilot.pause()

        run_tui(scenario)

    def test_bulk_delete_cancel_clears_restore(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                screen._restore_row = 4
                screen._on_bulk_delete("no")
                assert screen._restore_row is None

        run_tui(scenario)

    def test_bulk_delete_success_clears_marks(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                _sync_workers(monkeypatch, screen)
                monkeypatch.setattr(sessions_module, "delete_session", lambda *a, **k: CliResult([], 0, "", ""))
                screen._marked = {"ses1"}
                screen._on_bulk_delete("yes")
                assert screen._marked == set()

        run_tui(scenario)

    def test_bulk_delete_failure_sets_restore_none(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                _sync_workers(monkeypatch, screen)
                monkeypatch.setattr(sessions_module, "delete_session", lambda *a, **k: CliResult([], 1, "", "boom"))
                screen._marked = {"ses1"}
                screen._restore_row = 2
                screen._on_bulk_delete("yes")
                assert screen._restore_row is None

        run_tui(scenario)

    def test_delete_single_failure_keeps_row_hint_cleared(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                _sync_workers(monkeypatch, screen)
                monkeypatch.setattr(sessions_module, "delete_session", lambda *a, **k: CliResult([], 1, "", "nope"))
                screen._restore_row = 3
                screen._on_delete("yes", screen._all[0])
                assert screen._restore_row is None

        run_tui(scenario)

    def test_move_choice_with_backup_invokes_backup(self, run_tui, tui_env, monkeypatch, tmp_path):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                _sync_workers(monkeypatch, screen)
                calls: list[str] = []
                monkeypatch.setattr(sessions_module, "create_backup", lambda *a, **k: calls.append("backup"))
                fake = MoveResult(
                    session_id="ses1", from_directory="/work/dir", to_directory=str(tmp_path),
                    project_id="global", path="", moved_sessions=1,
                )
                monkeypatch.setattr(sessions_module, "move_session", lambda *a, **k: fake)
                screen._on_move_choice("move_backup", screen._all[0], tmp_path)
                assert calls == ["backup"]

        run_tui(scenario)

    def test_move_choice_cancel_does_nothing(self, run_tui, tui_env, monkeypatch, tmp_path):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                calls: list[str] = []
                monkeypatch.setattr(sessions_module, "move_session", lambda *a, **k: calls.append("move"))
                screen._on_move_choice("no", screen._all[0], tmp_path)
                assert calls == []

        run_tui(scenario)

    def test_rename_strips_title(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                _sync_workers(monkeypatch, screen)
                captured: list[str] = []
                monkeypatch.setattr(
                    sessions_module, "set_title",
                    lambda _cfg, _sid, title: captured.append(title) or True,
                )
                screen._on_rename("  New title  ", screen._all[0])
                assert captured == ["New title"]

        run_tui(scenario)

    def test_rename_whitespace_is_noop(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                _sync_workers(monkeypatch, screen)
                captured: list[str] = []
                monkeypatch.setattr(
                    sessions_module, "set_title",
                    lambda _cfg, _sid, title: captured.append(title) or True,
                )
                screen._on_rename("   ", screen._all[0])
                assert captured == []

        run_tui(scenario)

    def test_export_confirmation_gates_work(self, run_tui, tui_env, monkeypatch, tmp_path):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await _open_sessions(app, pilot)
                ran: list[Path] = []

                def work() -> Path:
                    ran.append(tmp_path / "out.md")
                    return tmp_path / "out.md"

                screen._on_export("no", work)
                assert ran == []
                _sync_workers(monkeypatch, screen)
                screen._on_export("yes", work)
                assert ran == [tmp_path / "out.md"]

        run_tui(scenario)


class TestDetailScreenActions:

    async def _open_detail(self, app, pilot) -> DetailScreen:
        screen = DetailScreen(_session_size())
        app.push_screen(screen)
        await settle(app, pilot)
        return screen

    def test_toggle_message_sort(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                assert screen._msg_desc is True
                assert len(screen._ordered) == 1
                screen.action_toggle_message_sort()
                assert screen._msg_desc is False

        run_tui(scenario)

    def test_export_json_builds_dest(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                captured: dict = {}
                monkeypatch.setattr(
                    screen, "_confirm_export",
                    lambda kind, dest, work: captured.update(kind=kind, dest=dest),
                )
                screen.action_export_json()
                assert captured["kind"] == "JSON"
                assert captured["dest"].name.endswith(".json")

        run_tui(scenario)

    def test_after_delete_success_pops(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                screen._after_delete(CliResult([], 0, "", ""))
                await pilot.pause()
                assert app.screen is not screen

        run_tui(scenario)

    def test_after_delete_failure_stays(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                screen._after_delete(CliResult([], 1, "", "boom"))
                await pilot.pause()
                assert app.screen is screen

        run_tui(scenario)

    def test_on_reload_missing_session_pops(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                await settle(app, pilot)
                screen._on_reload(None)
                await pilot.pause()
                assert app.screen is not screen

        run_tui(scenario)

    def test_on_reload_applies_new_size(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                updated = _session_size()
                updated.event_bytes = 999
                screen._on_reload(updated)
                assert screen.session is updated

        run_tui(scenario)

    def test_on_list_view_selected_opens_reply(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                await settle(app, pilot)
                screen.on_list_view_selected(SimpleNamespace(index=0))
                await pilot.pause()
                assert isinstance(app.screen, ReplyScreen)

        run_tui(scenario)

    def test_move_choice_backup_calls_backup(self, run_tui, tui_env, monkeypatch, tmp_path):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                _sync_workers(monkeypatch, screen)
                calls: list[str] = []
                monkeypatch.setattr(detail_module, "create_backup", lambda *a, **k: calls.append("backup"))
                fake = MoveResult(
                    session_id="ses1", from_directory="/work/dir", to_directory=str(tmp_path),
                    project_id="global", path="", moved_sessions=1,
                )
                monkeypatch.setattr(detail_module, "move_session", lambda *a, **k: fake)
                screen._on_move_choice("move_backup", tmp_path)
                assert calls == ["backup"]

        run_tui(scenario)

    def test_on_rename_returns_when_empty(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                calls: list = []
                monkeypatch.setattr(detail_module, "set_title", lambda *a, **k: calls.append(a))
                screen._on_rename("")
                assert calls == []

        run_tui(scenario)

    def test_on_rename_whitespace_is_noop(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                calls: list = []
                monkeypatch.setattr(detail_module, "set_title", lambda *a, **k: calls.append(a))
                screen._on_rename("   ")
                assert calls == []

        run_tui(scenario)

    def test_reload_keeps_existing_session(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                screen.reload()
                await settle(app, pilot)
                assert screen.session.session_id == "ses1"

        run_tui(scenario)

    def test_export_markdown_builds_dest(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                captured: dict = {}
                monkeypatch.setattr(
                    screen, "_confirm_export",
                    lambda kind, dest, work: captured.update(kind=kind, dest=dest),
                )
                screen.action_export_markdown()
                assert captured["kind"] == "Markdown"
                assert captured["dest"].name.endswith(".md")

        run_tui(scenario)

    def test_on_export_yes_runs_work(self, run_tui, tui_env, monkeypatch, tmp_path):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open_detail(app, pilot)
                _sync_workers(monkeypatch, screen)
                ran: list = []
                screen._on_export("yes", lambda: ran.append("done") or (tmp_path / "x.md"))
                assert ran == ["done"]

        run_tui(scenario)


class TestBrowseScreenActions:

    def test_selected_summary_matches_cursor(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                summary = screen._selected_summary()
                assert summary is not None
                assert summary.directory == "/work/dir"

        run_tui(scenario)

    def test_row_selected_opens_sessions(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                app.screen.on_data_table_row_selected(SimpleNamespace(cursor_row=0))
                await settle(app, pilot)
                assert isinstance(app.screen, SessionsScreen)

        run_tui(scenario)

    def test_show_footprint_safe_has_no_warning(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                report = ScanReport(entries=[
                    RootEntry(key="log", label="Log", path=Path("/x"), category="managed", size_bytes=10),
                ])
                screen._show_footprint((report, SafetyStatus(False, [])))
                text = str(screen.query_one("#summary", Static).content)
                assert "Total footprint" in text
                assert "Warning" not in text

        run_tui(scenario)

    def test_show_footprint_unsafe_adds_warning(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                report = ScanReport(entries=[
                    RootEntry(key="log", label="Log", path=Path("/x"), category="managed", size_bytes=10),
                ])
                screen._show_footprint((report, SafetyStatus(True, [])))
                text = str(screen.query_one("#summary", Static).content)
                assert "Warning" in text

        run_tui(scenario)

    def test_populate_fills_table(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                screen._populate([_dir_summary()])
                assert screen.query_one("#dirs", DataTable).row_count == 1

        run_tui(scenario)

    def test_delete_directory_cancel_is_noop(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                monkeypatch.setattr(browse_module, "delete_session", lambda *a, **k: pytest.fail("should not delete"))
                screen._on_delete_directory("no", _dir_summary())

        run_tui(scenario)

    def test_after_delete_directory_reports_failures(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                screen._after_delete_directory([("ses1", True, ""), ("ses2", False, "err")])
                await settle(app, pilot)
                assert screen.query_one("#dirs", DataTable).row_count == 1

        run_tui(scenario)


class TestBaseScreenMaintenance:

    def test_run_blocking_delivers_result(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                captured: list = []
                screen.run_blocking(lambda: 21, lambda value: captured.append(value * 2))
                await settle(app, pilot)
                assert captured == [42]

        run_tui(scenario)

    def test_run_blocking_reports_failure(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                notified: list = []
                monkeypatch.setattr(app, "notify", lambda *a, **k: notified.append(a))
                screen.run_blocking(lambda: (_ for _ in ()).throw(ValueError("boom")), lambda value: None)
                await settle(app, pilot)
                assert notified

        run_tui(scenario)

    def test_active_table_prefers_focused(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                table = screen.query_one("#dirs", DataTable)
                assert screen._active_table() is table

        run_tui(scenario)

    def test_copy_row_copies_table_text(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                copied: list[str] = []
                monkeypatch.setattr(app, "copy_to_clipboard", lambda text: copied.append(text))
                screen.action_copy_row()
                assert copied and "\t" in copied[0]

        run_tui(scenario)

    def test_copy_selection_without_selection_skips(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                with pytest.raises(SkipAction):
                    app.screen.action_copy_selection()

        run_tui(scenario)

    def test_run_blocking_with_overlay_mounts_and_cleans_up(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                captured: list = []
                screen.run_blocking(lambda: "done", captured.append, message="Working…")
                await settle(app, pilot)
                assert captured == ["done"]
                assert len(screen.query(LoadingOverlay)) == 0

        run_tui(scenario)

    def test_backup_action_opens_confirmation(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                app.screen.action_do_backup()
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                await pilot.press("escape")
                await pilot.pause()

        run_tui(scenario)

    def test_prune_and_vacuum_actions_open_confirmation(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                app.screen.action_do_prune()
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                await pilot.press("escape")
                await pilot.pause()
                app.screen.action_do_vacuum()
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                await pilot.press("escape")
                await pilot.pause()

        run_tui(scenario)

    def test_on_backup_cancel_skips(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                monkeypatch.setattr(base_module, "create_backup", lambda *a, **k: pytest.fail("should not back up"))
                screen._on_backup("no")

        run_tui(scenario)

    def test_on_backup_yes_creates_and_notifies(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                _sync_workers(monkeypatch, screen)
                result = BackupResult(path=Path("/b.zip"), db_bytes=1, total_bytes=2, extra_files=0)
                monkeypatch.setattr(base_module, "create_backup", lambda *a, **k: result)
                screen._on_backup("yes")
                await pilot.pause()

        run_tui(scenario)

    def test_prune_work_runs_all_steps(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                calls: list[str] = []
                monkeypatch.setattr(base_module, "prune", lambda *a, **k: calls.append("prune") or PruneResult())
                monkeypatch.setattr(base_module, "checkpoint", lambda *a, **k: calls.append("checkpoint"))
                monkeypatch.setattr(base_module, "clean_logs", lambda *a, **k: (calls.append("logs"), (0, 0))[1])
                monkeypatch.setattr(base_module, "create_backup", lambda *a, **k: None)
                result, logs = screen._prune_work(with_backup=True)
                assert calls == ["prune", "checkpoint", "logs"]
                assert logs == (0, 0)

        run_tui(scenario)

    def test_on_prune_cancel_skips(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                monkeypatch.setattr(screen, "run_blocking", lambda *a, **k: pytest.fail("should not run"))
                screen._on_prune("no")

        run_tui(scenario)

    def test_notify_prune_reloads(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                screen._notify_prune((PruneResult(orphan_event_sequences=1, orphan_event_bytes=4), (2, 10)))
                await settle(app, pilot)

        run_tui(scenario)

    def test_vacuum_runs_when_safe(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                _sync_workers(monkeypatch, screen)
                monkeypatch.setattr(base_module, "probe", lambda *a, **k: SafetyStatus(False, []))
                monkeypatch.setattr(base_module, "vacuum", lambda *a, **k: VacuumResult(before_bytes=10, after_bytes=5))
                screen._on_vacuum("yes")
                await pilot.pause()

        run_tui(scenario)

    def test_vacuum_cancel_skips(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                monkeypatch.setattr(screen, "run_blocking", lambda *a, **k: pytest.fail("should not run"))
                screen._on_vacuum("no")

        run_tui(scenario)


class TestBrowseDeleteDirectory:

    def test_delete_directory_work_runs_per_session(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = app.screen
                _sync_workers(monkeypatch, screen)
                deleted: list[str] = []
                monkeypatch.setattr(
                    browse_module, "delete_session",
                    lambda _cfg, sid, _dir: deleted.append(sid) or CliResult([], 0, "", ""),
                )
                summary = screen._selected_summary()
                screen._on_delete_directory("yes", summary)
                assert deleted == ["ses1"]

        run_tui(scenario)


class TestDashboardScreenActions:

    def test_populate_sorts_by_size_descending(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(DashboardScreen())
                await settle(app, pilot)
                screen = app.screen
                report = ScanReport(entries=[
                    RootEntry(key="a", label="A", path=Path("/a"), category="managed", size_bytes=10, exists=True),
                    RootEntry(key="b", label="B", path=Path("/b"), category="info", size_bytes=100, exists=False),
                ])
                screen._populate(screen._scan_token, report)
                table = screen.query_one("#roots", DataTable)
                assert table.get_row_at(0)[0] == "B"
                assert table.get_row_at(0)[1].plain.strip() == "100 B"

        run_tui(scenario)

    def test_row_selected_opens_browse(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(DashboardScreen())
                await settle(app, pilot)
                app.screen.on_data_table_row_selected(SimpleNamespace())
                await settle(app, pilot)
                assert isinstance(app.screen, BrowseScreen)

        run_tui(scenario)

    def test_populate_ignores_stale_scan_token(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(DashboardScreen())
                await settle(app, pilot)
                screen = app.screen
                table = screen.query_one("#roots", DataTable)
                before = table.row_count
                report = ScanReport(entries=[
                    RootEntry(key="a", label="A", path=Path("/a"), category="managed", size_bytes=10),
                ])
                screen._populate(screen._scan_token - 1, report)
                assert table.row_count == before

        run_tui(scenario)


class TestAppCommands:

    def test_persist_theme_saves_name(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test():
                captured: list[dict] = []
                monkeypatch.setattr(tui_app, "save_ui_overrides", lambda updates: captured.append(updates))
                app._persist_theme(SimpleNamespace(name="nord"))
                assert captured == [{"THEME": "nord"}]

        run_tui(scenario)

    def test_persist_theme_ignores_empty_name(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test():
                captured: list[dict] = []
                monkeypatch.setattr(tui_app, "save_ui_overrides", lambda updates: captured.append(updates))
                app._persist_theme(SimpleNamespace(name=""))
                assert captured == []

        run_tui(scenario)

    def test_theme_preview_does_not_persist(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = ThemePickerScreen()
                app.push_screen(screen)
                await pilot.pause()
                name = next(n for n in app.available_themes if not n.startswith("ansi"))
                captured: list[dict] = []
                monkeypatch.setattr(tui_app, "save_ui_overrides", lambda updates: captured.append(updates))
                screen.on_option_list_option_highlighted(SimpleNamespace(option=SimpleNamespace(id=name)))
                assert app.theme == name
                assert captured == []

        run_tui(scenario)

    def test_choice_screen_renders_dangerous_markup(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = ChoiceScreen("Delete [/]\n[red]x[/red]", [("Yes", "yes"), ("No", "no")])
                app.push_screen(screen)
                await pilot.pause()
                assert screen.is_attached

        run_tui(scenario)

    def test_loading_overlay_renders_dangerous_markup(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                overlay = LoadingOverlay("Working [/] now")
                app.screen.mount(overlay)
                await pilot.pause()
                assert overlay.is_attached

        run_tui(scenario)

    def test_info_panel_hide_and_show(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                summary = app.screen.query_one("#summary", Static)
                app.action_hide_info_panel()
                assert summary.display is False
                app.action_show_info_panel()
                assert summary.display is True

        run_tui(scenario)

    def test_system_commands_toggle_info_panel(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                titles = [command.title for command in app.get_system_commands(app.screen)]
                assert "Hide info panel" in titles
                app.action_hide_info_panel()
                titles = [command.title for command in app.get_system_commands(app.screen)]
                assert "Show info panel" in titles

        run_tui(scenario)

    def test_navigate_back_pops_screen(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(SessionsScreen(_dir_summary()))
                await settle(app, pilot)
                app.action_navigate_back()
                await pilot.pause()
                assert isinstance(app.screen, BrowseScreen)

        run_tui(scenario)

    def test_go_home_pops_to_default(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                app.push_screen(SessionsScreen(_dir_summary()))
                await settle(app, pilot)
                await app.action_go_home()
                await pilot.pause()
                assert isinstance(app.screen, BrowseScreen)

        run_tui(scenario)

    def test_database_backup_opens_confirmation(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                app.action_database_backup()
                await pilot.pause()
                assert isinstance(app.screen, ChoiceScreen)
                await pilot.press("escape")
                await pilot.pause()

        run_tui(scenario)

    def test_save_screenshot_success(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test():
                saved: list[dict] = []
                monkeypatch.setattr(app, "save_screenshot", lambda **kwargs: saved.append(kwargs) or Path("/shot.svg"))
                app._save_screenshot()
                assert saved

        run_tui(scenario)

    def test_save_screenshot_failure_is_handled(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test():
                def _boom(**_kwargs):
                    raise OSError("no space")

                monkeypatch.setattr(app, "save_screenshot", _boom)
                app._save_screenshot()  # must not raise

        run_tui(scenario)

    def test_action_push_screens(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                app.action_show_token_stats()
                await pilot.pause()
                assert isinstance(app.screen, StatsScreen)
                await pilot.press("escape")
                await pilot.pause()
                app.action_show_disk_stats()
                await pilot.pause()
                assert isinstance(app.screen, DashboardScreen)
                await pilot.press("escape")
                await pilot.pause()
                app.action_open_theme_picker()
                await pilot.pause()
                assert isinstance(app.screen, ThemePickerScreen)


class TestThemePicker:

    def test_select_option_applies_and_persists(self, run_tui, tui_env, monkeypatch):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = ThemePickerScreen()
                app.push_screen(screen)
                await pilot.pause()
                name = next(n for n in app.available_themes if not n.startswith("ansi"))
                saved: list[dict] = []
                dismissed: list = []
                monkeypatch.setattr(theme_module, "save_ui_overrides", lambda updates: saved.append(updates))
                monkeypatch.setattr(screen, "dismiss", lambda value=None: dismissed.append(value))
                screen.on_option_list_option_selected(SimpleNamespace(option=SimpleNamespace(id=name)))
                assert app.theme == name
                assert saved == [{"THEME": name}]
                assert dismissed == [name]

        run_tui(scenario)

    def test_highlight_previews_theme(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                screen = ThemePickerScreen()
                app.push_screen(screen)
                await pilot.pause()
                name = next(n for n in app.available_themes if not n.startswith("ansi"))
                screen.on_option_list_option_highlighted(SimpleNamespace(option=SimpleNamespace(id=name)))
                assert app.theme == name

        run_tui(scenario)

    def test_copy_or_cancel_empty_restores_and_dismisses(self, run_tui, tui_env):
        tui_env()

        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                await settle(app, pilot)
                original = app.theme
                screen = ThemePickerScreen()
                app.push_screen(screen)
                await pilot.pause()
                dismissed: list = []

                def _dismiss(value=None):
                    dismissed.append(value)

                screen.dismiss = _dismiss
                app.theme = next(n for n in app.available_themes if not n.startswith("ansi"))
                screen.action_copy_or_cancel()
                assert dismissed == [None]
                assert app.theme == original

        run_tui(scenario)


class TestConfirmScreen:

    async def _open(self, app, pilot, options, title="Confirm"):
        screen = ChoiceScreen("Message?", options, title=title)
        app.push_screen(screen)
        await pilot.pause()
        return screen

    def test_on_mount_focuses_cancel(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot, [("Yes", "yes"), ("No", "no")])
                assert app.focused is not None
                assert screen.focused.id == "no"

        run_tui(scenario)

    def test_on_mount_focuses_last_without_cancel(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot, [("Alpha", "a"), ("Beta", "b")])
                assert screen.focused.id == "b"

        run_tui(scenario)

    def test_button_pressed_dismisses_with_id(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot, [("Yes", "yes"), ("No", "no")])
                dismissed: list = []
                screen.dismiss = lambda value=None: dismissed.append(value)
                screen.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="yes")))
                assert dismissed == ["yes"]

        run_tui(scenario)

    def test_copy_or_cancel_empty_dismisses_none(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot, [("Yes", "yes"), ("No", "no")])
                dismissed: list = []
                screen.dismiss = lambda value=None: dismissed.append(value)
                screen.action_copy_or_cancel()
                assert dismissed == [None]

        run_tui(scenario)

    def test_on_mount_without_buttons_is_safe(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot, [])
                assert app.screen is screen

        run_tui(scenario)

    def test_focus_navigation_actions(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot, [("Yes", "yes"), ("No", "no")])
                screen.action_focus_previous()
                assert screen.focused is not None
                screen.action_focus_next()
                assert screen.focused is not None

        run_tui(scenario)


class TestPromptScreen:

    async def _open(self, app, pilot):
        screen = TextPromptScreen("Title?", initial="x")
        app.push_screen(screen)
        await pilot.pause()
        return screen

    def test_button_ok_dismisses_with_input(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot)
                screen.query_one("#dialog-input", Input).value = "typed"
                dismissed: list = []
                screen.dismiss = lambda value=None: dismissed.append(value)
                screen.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="ok")))
                assert dismissed == ["typed"]

        run_tui(scenario)

    def test_button_cancel_dismisses_none(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot)
                dismissed: list = []
                screen.dismiss = lambda value=None: dismissed.append(value)
                screen.on_button_pressed(SimpleNamespace(button=SimpleNamespace(id="cancel")))
                assert dismissed == [None]

        run_tui(scenario)

    def test_action_cancel_dismisses_none(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot)
                dismissed: list = []
                screen.dismiss = lambda value=None: dismissed.append(value)
                screen.action_cancel()
                assert dismissed == [None]

        run_tui(scenario)

    def test_copy_or_cancel_empty_dismisses_none(self, run_tui):
        async def scenario():
            app = OcduApp()
            async with app.run_test() as pilot:
                screen = await self._open(app, pilot)
                dismissed: list = []
                screen.dismiss = lambda value=None: dismissed.append(value)
                screen.action_copy_or_cancel()
                assert dismissed == [None]

        run_tui(scenario)


