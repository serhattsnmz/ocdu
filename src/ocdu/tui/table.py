"""DataTable with explicit row activation and copy-friendly row text.

Textual dispatches ``_on_click`` for every class in the widget's MRO, so
overriding it is not enough: ``DataTable._on_click`` still runs and posts
``RowSelected`` when the clicked row is already the cursor row. This subclass
suppresses that click-driven selection (while keeping Enter working), so a
single click only moves the cursor, a double click activates the row, and the
cursor row can be copied as tab-separated text.
"""

from __future__ import annotations
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.coordinate import Coordinate
from textual.widgets import DataTable

class CopyableDataTable(DataTable):
    """A ``DataTable`` that selects on click and can yield its row as text."""

    BINDINGS = [
        Binding("end", "scroll_bottom", "End", show=False),
        Binding("home", "scroll_top", "Home", show=False),
    ]

    _in_click = False

    copy_skip_first = False
    """When True, ``row_text`` omits the first column (a leading marker column)."""

    @staticmethod
    def _cell_text(value: object) -> str:
        """Return the plain text of a cell with newlines flattened."""
        if isinstance(value, Text):
            return value.plain.replace("\n", " ")
        return Text.from_markup(str(value)).plain.replace("\n", " ")

    def row_text(self, row_index: int | None = None) -> str | None:
        """Return a row (default: the cursor row) as tab-separated text."""
        index = self.cursor_row if row_index is None else row_index
        if not (0 <= index < self.row_count):
            return None
        cells = self.get_row_at(index)
        if self.copy_skip_first:
            cells = cells[1:]
        return "\t".join(self._cell_text(cell) for cell in cells)

    def _post_selected_message(self) -> None:
        """Post a row-selected message unless a click is being handled."""
        if self._in_click:
            return
        super()._post_selected_message()

    def _reset_click(self) -> None:
        """Clear the click-handling flag."""
        self._in_click = False

    async def _on_click(self, event: events.Click) -> None:
        """Move the cursor on click; activate the row on a double click."""
        meta = event.style.meta
        if "row" not in meta or "column" not in meta:
            return
        if self.cursor_type != "row" and meta.get("out_of_bounds", False):
            return
        row_index = meta["row"]
        column_index = meta["column"]
        if row_index < 0 or column_index < 0:
            return

        self._in_click = True
        try:
            self.cursor_coordinate = Coordinate(row_index, column_index)
            if event.chain == 2:
                DataTable._post_selected_message(self)
        finally:
            self.call_later(self._reset_click)
