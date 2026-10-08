"""Headless tests for ocdu.tui widgets (table, list view, loading overlay)."""

from __future__ import annotations
from types import SimpleNamespace
from rich.text import Text
from textual.app import App, ComposeResult
from textual.coordinate import Coordinate
from textual.widgets import DataTable, Label, Static
from ocdu.tui.listview import ClickSelectItem, ClickSelectListView
from ocdu.tui.loading import LoadingOverlay
from ocdu.tui.table import CopyableDataTable

class _TableApp(App):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.selected: list = []

    def compose(self) -> ComposeResult:
        yield CopyableDataTable(id="t")

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        self.selected.append(event)

class _ListApp(App):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.selected: list = []

    def compose(self) -> ComposeResult:
        yield ClickSelectListView(
            ClickSelectItem(Label("a")), ClickSelectItem(Label("b")), id="l"
        )

    def on_list_view_selected(self, event: ClickSelectListView.Selected) -> None:
        self.selected.append(event)

class _EmptyListApp(App):
    def compose(self) -> ComposeResult:
        yield ClickSelectListView(id="l")

class _LoadingApp(App):
    def compose(self) -> ComposeResult:
        yield LoadingOverlay("working")

def _click(chain: int = 1, row: int = 0, column: int = 0) -> SimpleNamespace:
    """Build a minimal click event shaped for ``CopyableDataTable._on_click``."""
    return SimpleNamespace(style=SimpleNamespace(meta={"row": row, "column": column}), chain=chain)

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

    def test_single_click_moves_cursor_without_selecting(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test() as pilot:
                table = app.query_one("#t", CopyableDataTable)
                table.cursor_type = "row"
                table.add_columns("A", "B")
                table.add_row("x", "y")
                table.add_row("p", "q")
                await table._on_click(_click(chain=1, row=1, column=0))
                await pilot.pause()
                assert table.cursor_coordinate == Coordinate(1, 0)
                assert app.selected == []

        run_tui(scenario)

    def test_double_click_posts_row_selected(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test() as pilot:
                table = app.query_one("#t", CopyableDataTable)
                table.cursor_type = "row"
                table.add_columns("A", "B")
                table.add_row("x", "y")
                await table._on_click(_click(chain=2, row=0, column=0))
                await pilot.pause()
                assert len(app.selected) == 1

        run_tui(scenario)

    def test_click_missing_coordinates_is_ignored(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test() as pilot:
                table = app.query_one("#t", CopyableDataTable)
                table.add_columns("A")
                table.add_row("x")
                event = SimpleNamespace(style=SimpleNamespace(meta={}), chain=1)
                await table._on_click(event)
                await pilot.pause()
                assert app.selected == []

        run_tui(scenario)

    def test_post_selected_suppressed_during_click(self, run_tui):
        async def scenario():
            app = _TableApp()
            async with app.run_test() as pilot:
                table = app.query_one("#t", CopyableDataTable)
                table.cursor_type = "row"
                table.add_columns("A")
                table.add_row("x")
                table._in_click = True
                table._post_selected_message()
                await pilot.pause()
                assert app.selected == []
                table._reset_click()
                table._post_selected_message()
                await pilot.pause()
                assert len(app.selected) == 1

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

    def test_single_click_selects_without_activating(self, run_tui):
        async def scenario():
            app = _ListApp()
            async with app.run_test():
                widget = app.query_one("#l", ClickSelectListView)
                item = widget._nodes[1]
                item.last_chain = 1
                event = SimpleNamespace(item=item, stop=lambda: None)
                widget._on_list_item__child_clicked(event)
                assert widget.index == 1

        run_tui(scenario)

    def test_double_click_posts_selected(self, run_tui):
        async def scenario():
            app = _ListApp()
            async with app.run_test() as pilot:
                widget = app.query_one("#l", ClickSelectListView)
                item = widget._nodes[0]
                item.last_chain = 2
                event = SimpleNamespace(item=item, stop=lambda: None)
                widget._on_list_item__child_clicked(event)
                await pilot.pause()
                assert len(app.selected) == 1

        run_tui(scenario)

    def test_item_click_records_chain(self, run_tui):
        async def scenario():
            app = _ListApp()
            async with app.run_test():
                widget = app.query_one("#l", ClickSelectListView)
                item = widget._nodes[0]
                event = SimpleNamespace(chain=2)
                item._on_click(event)
                assert item.last_chain == 2
                assert event._no_default_action is True

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

