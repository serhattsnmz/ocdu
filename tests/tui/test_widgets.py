"""Headless tests for ocdu.tui widgets (table, list view, loading overlay)."""

from __future__ import annotations
from rich.text import Text
from textual.app import App, ComposeResult
from textual.widgets import Label, Static
from ocdu.tui.listview import ClickSelectItem, ClickSelectListView
from ocdu.tui.loading import LoadingOverlay
from ocdu.tui.table import CopyableDataTable

class _TableApp(App):
    def compose(self) -> ComposeResult:
        yield CopyableDataTable(id="t")

class _ListApp(App):
    def compose(self) -> ComposeResult:
        yield ClickSelectListView(
            ClickSelectItem(Label("a")), ClickSelectItem(Label("b")), id="l"
        )

class _EmptyListApp(App):
    def compose(self) -> ComposeResult:
        yield ClickSelectListView(id="l")

class _LoadingApp(App):
    def compose(self) -> ComposeResult:
        yield LoadingOverlay("working")

class TestCopyableDataTable:

    def test_row_text_joins_with_tabs(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test():
                table = app.query_one("#t", CopyableDataTable)
                table.add_columns("A", "B")
                table.add_row("x", "y")
                assert table.row_text() == "x\ty"

        run_tui(scenario)

    def test_copy_skip_first(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test():
                table = app.query_one("#t", CopyableDataTable)
                table.add_columns("A", "B")
                table.add_row("x", "y")
                table.copy_skip_first = True
                assert table.row_text() == "y"

        run_tui(scenario)

    def test_row_text_out_of_range(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test():
                table = app.query_one("#t", CopyableDataTable)
                table.add_columns("A")
                table.add_row("x")
                assert table.row_text(99) is None

        run_tui(scenario)

    def test_flattens_text_and_markup_cells(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test():
                table = app.query_one("#t", CopyableDataTable)
                table.add_columns("A", "B")
                table.add_row(Text("a\nb"), "[red]c[/]")
                assert table.row_text() == "a b\tc"

        run_tui(scenario)

class TestClickSelectListView:

    def test_select_last_and_first(self, run_tui):
        async def scenario():
            app = _ListApp()
            async with app.run_test():
                widget = app.query_one("#l", ClickSelectListView)
                widget.action_select_last()
                assert widget.index == 1
                widget.action_select_first()
                assert widget.index == 0

        run_tui(scenario)

    def test_empty_list_actions_are_safe(self, run_tui):
        async def scenario():
            app = _EmptyListApp()
            async with app.run_test():
                widget = app.query_one("#l", ClickSelectListView)
                widget.action_select_last()
                widget.action_select_first()
                assert len(widget) == 0
                assert widget.index is None

        run_tui(scenario)

class TestLoadingOverlay:

    def test_composes_spinner_and_message(self, run_tui):
        async def scenario():
            app = _LoadingApp()
            async with app.run_test():
                overlay = app.query_one(LoadingOverlay)
                assert overlay.message == "working"
                message = app.query_one("#loading-message", Static)
                assert message is not None

        run_tui(scenario)
