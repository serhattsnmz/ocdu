"""Statistics screen: token/cost breakdown."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static
from rich.text import Text
from ...config import config
from ...db import Database
from ...stats import StatsReport, token_stats
from ...util import strip_control
from ..format import (
    COST_WIDTH,
    COUNT_WIDTH,
    TOKEN_WIDTH,
    cost_text,
    count_text,
    header_text,
    shorten_home,
    token_text,
)
from ..table import CopyableDataTable
from .base import OcduScreen

class StatsScreen(OcduScreen):
    """Shows token and cost totals plus breakdowns by model and directory."""

    BINDINGS = [Binding("y", "copy_row", "Copy row")]

    def compose(self) -> ComposeResult:
        """Compose the header, summary and table views."""
        yield Header()
        yield Static("Loading…", id="summary")
        yield CopyableDataTable(id="models")
        yield CopyableDataTable(id="dirs")
        yield Footer()

    def on_mount(self) -> None:
        """Configure the model and directory tables and load data."""
        models = self.query_one("#models", DataTable)
        models.cursor_type = "row"
        models.add_columns(
            header_text("Tokens", TOKEN_WIDTH),
            header_text("Cost", COST_WIDTH),
            header_text("Sessions", COUNT_WIDTH),
            "Model",
        )
        dirs = self.query_one("#dirs", DataTable)
        dirs.cursor_type = "row"
        dirs.add_columns(
            header_text("Tokens", TOKEN_WIDTH),
            header_text("Cost", COST_WIDTH),
            header_text("Sessions", COUNT_WIDTH),
            "Directory",
        )
        self.reload()

    def reload(self) -> None:
        """Reload the statistics in a worker thread."""
        self.run_blocking(self._load, self._populate)

    def _load(self) -> StatsReport:
        """Compute the statistics report from the database."""
        db = Database(config.db_path)
        with db.open() as connection:
            return token_stats(db, connection)

    def _populate(self, report: StatsReport) -> None:
        """Fill the summary and tables from the computed report."""
        totals = report.totals
        self.query_one("#summary", Static).update(
            f"Sessions: {totals.sessions}   |   tokens in: {totals.tokens_input:,}   "
            f"|   tokens out: {totals.tokens_output:,}   |   total cost: ${totals.cost:,.2f}"
        )
        models = self.query_one("#models", DataTable)
        models.clear()
        for stat in sorted(report.by_model, key=lambda s: s.tokens, reverse=True)[:20]:
            model_label = f"{strip_control(stat.provider)}/{strip_control(stat.model)}"
            models.add_row(
                token_text(stat.tokens), cost_text(stat.cost),
                count_text(stat.sessions), Text(model_label),
            )
        dirs = self.query_one("#dirs", DataTable)
        dirs.clear()
        for stat in sorted(report.by_directory, key=lambda s: s.tokens, reverse=True)[:20]:
            dirs.add_row(
                token_text(stat.tokens), cost_text(stat.cost),
                count_text(stat.sessions), Text(strip_control(shorten_home(stat.directory))),
            )
