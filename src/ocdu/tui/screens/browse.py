"""Browse: OpenCode session directories — the ocdu home screen."""

from __future__ import annotations
from datetime import datetime
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static
from rich.markup import escape
from rich.text import Text
from ...analyze import directory_summaries, scan_roots
from ...config import config
from ...db import Database
from ...model import CATEGORY_ORDER, DirectorySummary, ScanReport
from ...opencode import delete_session
from ...paths import build_roots
from ...safety import SafetyStatus, probe
from ...util import format_time, human_size, strip_control
from ..format import COUNT_WIDTH, SIZE_WIDTH, count_text, header_text, shorten_home, size_text
from ..table import CopyableDataTable
from .base import OcduScreen
from .confirm import ChoiceScreen
from .sessions import SessionsScreen

class BrowseScreen(OcduScreen):
    """Home screen: session directories plus the footprint info panel."""

    BINDINGS = [
        Binding("y", "copy_row", "Copy row"),
        Binding("d", "delete_directory", "Delete dir"),
    ]

    def __init__(self) -> None:
        """Initialize the screen with an empty summary list."""
        super().__init__()
        self.summaries: list[DirectorySummary] = []

    def compose(self) -> ComposeResult:
        """Compose the header, info panel, directory table and footer."""
        yield Header()
        yield Static("Loading…", id="summary")
        yield CopyableDataTable(id="dirs")
        yield Footer()

    def on_mount(self) -> None:
        """Configure the directory table and load the data."""
        table = self.query_one("#dirs", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(
            header_text("Size", SIZE_WIDTH),
            header_text("Sessions", COUNT_WIDTH),
            header_text("Roots", COUNT_WIDTH),
            "Exists",
            "Last used",
            "Directory",
        )
        self.reload()

    def reload(self) -> None:
        """Reload directory summaries and the footprint panel."""
        self.run_blocking(self._load, self._populate)
        self.reload_footprint()

    def _load(self) -> list[DirectorySummary]:
        """Load directory summaries from the database."""
        db = Database(config.db_path)
        with db.open() as connection:
            return directory_summaries(db, connection)

    def _populate(self, summaries: list[DirectorySummary]) -> None:
        """Fill the directory table with the loaded summaries."""
        self.summaries = summaries
        table = self.query_one("#dirs", DataTable)
        table.clear()
        for summary in summaries:
            table.add_row(
                size_text(summary.size_bytes),
                count_text(summary.session_count),
                count_text(summary.root_count),
                "yes" if summary.exists else "[red]no[/]",
                format_time(summary.last_updated),
                Text(strip_control(shorten_home(summary.directory))),
            )

    # -- footprint info panel (moved here from the disk-stats screen) --------
    def reload_footprint(self) -> None:
        """Rescan data roots and refresh the footprint panel."""
        self.query_one("#summary", Static).update("Scanning data roots…")
        self.run_blocking(self._scan_footprint, self._show_footprint)

    def _scan_footprint(self) -> tuple[ScanReport, SafetyStatus]:
        """Scan data roots and probe the environment."""
        status = probe(config)
        report = scan_roots(build_roots(config))
        return report, status

    def _show_footprint(self, data: tuple[ScanReport, SafetyStatus]) -> None:
        """Render the footprint panel from the scan result."""
        report, status = data
        by_category: dict[str, int] = {}
        for entry in report.entries:
            by_category[entry.category] = by_category.get(entry.category, 0) + entry.size_bytes
        ordered = [c for c in CATEGORY_ORDER if c in by_category]
        ordered += [c for c in by_category if c not in CATEGORY_ORDER]
        breakdown = "   ".join(
            f"{category}: {human_size(by_category[category])}" for category in ordered
        )
        lines = [
            f"Total footprint: [bold]{human_size(report.total_bytes)}[/]",
            f"Breakdown: {breakdown}",
            f"Data dir: {escape(shorten_home(config.data_dir))}",
            f"Updated: {datetime.now():%H:%M:%S}",
        ]
        if not status.safe_for_exclusive:
            lines.append(f"[bold red]Warning:[/] {status.describe()}")
            lines.append("[bold red]Close OpenCode before VACUUM.[/]")
        self.query_one("#summary", Static).update("\n".join(lines))

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the selected directory's session list."""
        index = event.cursor_row
        if 0 <= index < len(self.summaries):
            self.app.push_screen(SessionsScreen(self.summaries[index]))

    # -- delete every session in one directory -------------------------------
    def _selected_summary(self) -> DirectorySummary | None:
        """Return the directory at the cursor, or ``None``."""
        table = self.query_one("#dirs", DataTable)
        index = table.cursor_row
        if 0 <= index < len(self.summaries):
            return self.summaries[index]
        return None

    def action_delete_directory(self) -> None:
        """Delete every root session in the selected directory."""
        summary = self._selected_summary()
        if summary is None:
            return
        self.app.push_screen(
            ChoiceScreen(
                f"Delete ALL {summary.root_count} root session(s) in this directory?\n\n"
                f"{summary.directory}\n"
                f"Total sessions (children included): {summary.session_count}\n"
                f"Size: {human_size(summary.size_bytes)}",
                [("Delete all", "yes"), ("Cancel", "no")],
                title="Delete directory sessions",
            ),
            lambda choice: self._on_delete_directory(choice, summary),
        )

    def _on_delete_directory(self, choice: str | None, summary: DirectorySummary) -> None:
        """Handle the directory delete confirmation choice."""
        if choice != "yes":
            return

        def work() -> list[tuple[str, bool, str]]:
            """Delete each root session in the directory and collect results."""
            db = Database(config.db_path)
            with db.open() as connection:
                session_ids = db.root_session_ids(connection, summary.directory)
            results: list[tuple[str, bool, str]] = []
            for session_id in session_ids:
                try:
                    result = delete_session(config, session_id, summary.directory)
                    results.append((session_id, result.ok, result.stderr))
                except Exception as error:  # noqa: BLE001 - report per-session failure
                    results.append((session_id, False, str(error)))
            return results

        self.run_blocking(
            work,
            self._after_delete_directory,
            message=f"Deleting sessions in {shorten_home(summary.directory)}…",
        )

    def _after_delete_directory(self, results: list[tuple[str, bool, str]]) -> None:
        """Report the bulk delete results and reload."""
        ok = [r for r in results if r[1]]
        failed = [r for r in results if not r[1]]
        if failed:
            self.app.notify(
                f"Deleted {len(ok)} session(s), {len(failed)} failed.",
                severity="error",
                timeout=12,
            )
        else:
            self.app.notify(f"Deleted {len(ok)} session(s).", timeout=8)
        self.reload()
