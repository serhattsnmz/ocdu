"""Disk stats: sizes of every OpenCode data root in a single view."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header
from rich.text import Text
from ...analyze import scan_roots
from ...config import config
from ...model import RootEntry, ScanReport
from ...paths import build_roots
from ...util import strip_control
from ..format import COUNT_WIDTH, SIZE_WIDTH, count_text, header_text, shorten_home, size_text
from ..table import CopyableDataTable
from .base import OcduScreen
from .browse import BrowseScreen

CATEGORY_STYLE = {
    "managed": "bold cyan",
    "info": "yellow",
    "locked": "dim",
    "backup": "green",
}

class DashboardScreen(OcduScreen):
    """Shows the footprint of every tracked OpenCode data root."""

    BINDINGS = [Binding("y", "copy_row", "Copy row")]

    def __init__(self) -> None:
        """Initialize the screen with an empty root list."""
        super().__init__()
        self._roots: list[RootEntry] = []
        self._scan_token = 0

    def compose(self) -> ComposeResult:
        """Compose the header, root table and footer."""
        yield Header()
        yield CopyableDataTable(id="roots")
        yield Footer()

    def on_mount(self) -> None:
        """Build the roots table and start scanning."""
        table = self.query_one("#roots", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(
            ("Label", "label"),
            (header_text("Size", SIZE_WIDTH), "size"),
            (header_text("Files", COUNT_WIDTH), "files"),
            ("Category", "category"),
            ("Exists", "exists"),
            ("Path", "path"),
        )
        self._roots = build_roots(config)
        for entry in self._roots:
            table.add_row(
                entry.label,
                "…",
                "…",
                "…",
                "…",
                Text(strip_control(str(entry.path))),
                key=entry.key,
            )
        if config.tui_refresh_seconds > 0:
            self.set_interval(config.tui_refresh_seconds, self.reload)
        self.reload()

    def reload(self) -> None:
        """Start a fresh scan, ignoring results from older scans."""
        self._scan_token += 1
        token = self._scan_token
        self.run_blocking(
            lambda: self._scan(token),
            lambda report: self._populate(token, report),
        )

    def _scan(self, token: int) -> ScanReport:
        """Scan all roots and report each entry as it finishes."""
        return scan_roots(self._roots, on_entry=lambda entry: self._entry_ready(token, entry))

    def _entry_ready(self, token: int, entry: RootEntry) -> None:
        """Marshal a finished entry to the UI thread."""
        self.app.call_from_thread(self._update_row, token, entry)

    def _update_row(self, token: int, entry: RootEntry) -> None:
        """Update the table row for a finished entry."""
        if token != self._scan_token:
            return
        table = self.query_one("#roots", DataTable)
        style = CATEGORY_STYLE.get(entry.category, "")
        table.update_cell(entry.key, "label", entry.label)
        table.update_cell(entry.key, "size", size_text(entry.size_bytes))
        table.update_cell(entry.key, "files", count_text(entry.file_count))
        table.update_cell(
            entry.key,
            "category",
            f"[{style}]{entry.category}[/]" if style else entry.category,
        )
        table.update_cell(entry.key, "exists", "yes" if entry.exists else "no")
        table.update_cell(entry.key, "path", Text(strip_control(shorten_home(entry.path))))

    def _append_row(self, table: DataTable, entry: RootEntry) -> None:
        """Append a fully-populated row for one root entry."""
        style = CATEGORY_STYLE.get(entry.category, "")
        table.add_row(
            entry.label,
            size_text(entry.size_bytes),
            count_text(entry.file_count),
            f"[{style}]{entry.category}[/]" if style else entry.category,
            "yes" if entry.exists else "no",
            Text(strip_control(shorten_home(entry.path))),
            key=entry.key,
        )

    def _populate(self, token: int, report: ScanReport) -> None:
        """Rebuild the table from a finished scan, sorted by size."""
        if token != self._scan_token:
            return
        table = self.query_one("#roots", DataTable)
        table.clear()
        for entry in sorted(report.entries, key=lambda e: e.size_bytes, reverse=True):
            self._append_row(table, entry)

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the browse screen when a row is activated."""
        self.app.push_screen(BrowseScreen())
