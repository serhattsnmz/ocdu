"""Headless tests for the ocdu Textual app and its screens."""

from __future__ import annotations
from textual.widgets import DataTable, Input
from ocdu.model import DirectorySummary, MessageTurn, SessionSize
from ocdu.tui.app import OcduApp
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
