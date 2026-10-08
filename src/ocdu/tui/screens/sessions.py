"""Sessions: sessions inside one working directory."""

from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static
from rich.markup import escape
from rich.text import Text
from ...analyze import session_sizes
from ...backup import create_backup
from ...config import config
from ...db import Database
from ...export import TranscriptOptions, export_json, export_markdown, safe_filename
from ...model import DirectorySummary, SessionSize
from ...move import MoveResult, move_session
from ...opencode import CliResult, delete_session
from ...session_ops import set_title
from ...state import pinned_session_ids
from ...util import format_time, human_size, strip_control
from ..format import (
    COST_WIDTH,
    COUNT_WIDTH,
    SIZE_WIDTH,
    cost_text,
    count_text,
    header_text,
    shorten_home,
    size_text,
)
from ..table import CopyableDataTable
from .base import OcduScreen
from .confirm import ChoiceScreen
from .detail import DetailScreen
from .prompt import TextPromptScreen

# Sort cycle order; the first entry is the default (size, descending).
_SORT_CYCLE: tuple[tuple[str, bool], ...] = (
    ("size", True),
    ("size", False),
    ("time", True),
    ("time", False),
)
_SORT_ARROW = {True: "↓", False: "↑"}

class SessionsScreen(OcduScreen):
    """Lists root sessions for a directory (children aggregated)."""

    BINDINGS = OcduScreen.BINDINGS + [
        Binding("y", "copy_row", "Copy row"),
        Binding("d", "delete_selected", "Delete"),
        Binding("space", "toggle_mark", "Mark"),
        Binding("m", "move_selected", "Move"),
        Binding("n", "rename_selected", "Rename"),
        Binding("slash", "filter", "Filter"),
        Binding("o", "toggle_sort", "Sort"),
        Binding("e", "export_markdown", "Export MD"),
        Binding("j", "export_json", "Export JSON"),
    ]

    def __init__(self, directory: DirectorySummary) -> None:
        """Store the directory and initialize list state."""
        super().__init__()
        self.directory = directory
        self._all: list[SessionSize] = []
        self.sessions: list[SessionSize] = []
        self.filter_text = ""
        self.sort_index = 0
        self._marked: set[str] = set()
        self._pinned: set[str] = set()
        self._restore_row: int | None = None
        self._mark_column: object | None = None

    def compose(self) -> ComposeResult:
        """Compose the header, summary and session table."""
        yield Header()
        yield Static("Loading…", id="summary")
        yield CopyableDataTable(id="sessions")
        yield Footer()

    def on_mount(self) -> None:
        """Configure the session table and load the data."""
        table = self.query_one("#sessions", CopyableDataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.copy_skip_first = True
        keys = table.add_columns(
            "",
            header_text("Size", SIZE_WIDTH),
            header_text("Msg", COUNT_WIDTH),
            header_text("Child", COUNT_WIDTH),
            header_text("Cost", COST_WIDTH),
            header_text("★", 2),
            "Updated",
            "Title",
        )
        self._mark_column = keys[0]
        self.reload()

    def reload(self) -> None:
        """Reload the sessions for this directory."""
        self.run_blocking(self._load, self._set_data)

    def _load(self) -> list[SessionSize]:
        """Load the root sessions that belong to this directory."""
        db = Database(config.db_path)
        with db.open() as connection:
            sessions = session_sizes(db, connection, roots_only=True)
        target = self.directory.directory
        return [s for s in sessions if s.directory == target]

    def _set_data(self, sessions: list[SessionSize]) -> None:
        """Store the loaded sessions and pinned ids, then rebuild."""
        self._all = sessions
        self._pinned = pinned_session_ids(config)
        self._rebuild()

    def _rebuild(self) -> None:
        """Filter, sort and repopulate the session table."""
        data = list(self._all)
        if self.filter_text:
            needle = self.filter_text.lower()
            data = [s for s in data if needle in s.title.lower()]
        field, descending = _SORT_CYCLE[self.sort_index]
        key = (lambda s: s.time_updated) if field == "time" else (lambda s: s.total_bytes)
        data.sort(key=key, reverse=descending)
        self.sessions = data

        table = self.query_one("#sessions", CopyableDataTable)
        table.clear()
        for session in data:
            table.add_row(
                self._marker(session.session_id in self._marked),
                size_text(session.total_bytes),
                count_text(session.message_count),
                count_text(session.child_count),
                cost_text(session.cost),
                self._star(session.session_id),
                format_time(session.time_updated),
                Text(strip_control(session.title)),
                key=session.session_id,
            )
        self._render_summary()
        self._restore_cursor()

    def _marker(self, marked: bool) -> Text:
        """Return the marker cell for a marked session."""
        return Text("▸", style="bold green") if marked else Text(" ")

    def _star(self, session_id: str) -> Text:
        """Return the star cell for a pinned session."""
        return Text("★", style="yellow") if session_id in self._pinned else Text(" ")

    def _render_summary(self) -> None:
        """Update the summary line with counts, size and active flags."""
        field, descending = _SORT_CYCLE[self.sort_index]
        total = sum(s.total_bytes for s in self.sessions)
        flags = []
        if self.filter_text:
            flags.append(f"filter='{escape(self.filter_text)}'")
        flags.append(f"sort={field}{_SORT_ARROW[descending]}")
        if self._marked:
            flags.append(f"{len(self._marked)} marked")
        extra = "  |  " + ", ".join(flags)
        self.query_one("#summary", Static).update(
            f"{escape(shorten_home(self.directory.directory))} — {len(self.sessions)} sessions, "
            f"{human_size(total)} total{extra}"
        )

    def _restore_cursor(self) -> None:
        """Restore the cursor to the saved row after a rebuild."""
        if self._restore_row is None:
            return
        target = self._restore_row
        self._restore_row = None
        if not self.sessions:
            return

        def move() -> None:
            """Move the cursor to the restored row."""
            table = self.query_one("#sessions", CopyableDataTable)
            if table.row_count:
                table.move_cursor(row=max(0, min(target, table.row_count - 1)))

        self.call_after_refresh(move)

    # -- selection -----------------------------------------------------------
    def _selected(self) -> SessionSize | None:
        """Return the session at the cursor, or ``None``."""
        table = self.query_one("#sessions", DataTable)
        index = table.cursor_row
        if 0 <= index < len(self.sessions):
            return self.sessions[index]
        return None

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        """Open the detail screen for the selected session."""
        session_id = event.row_key.value
        for session in self.sessions:
            if session.session_id == session_id:
                self.app.push_screen(DetailScreen(session))
                return

    # -- filter / sort -------------------------------------------------------
    def action_filter(self) -> None:
        """Prompt for a title filter."""
        self.app.push_screen(
            TextPromptScreen("Title contains (empty to clear):", title="Filter", initial=self.filter_text),
            self._on_filter,
        )

    def _on_filter(self, value: str | None) -> None:
        """Apply the entered filter text and rebuild the list."""
        if value is None:
            return
        self.filter_text = value.strip()
        self._rebuild()

    def action_toggle_sort(self) -> None:
        """Advance to the next sort mode and rebuild the list."""
        self.sort_index = (self.sort_index + 1) % len(_SORT_CYCLE)
        self._rebuild()

    # -- mark (multi-select) -------------------------------------------------
    def action_toggle_mark(self) -> None:
        """Toggle the marked state of the selected session."""
        session = self._selected()
        if session is None:
            return
        session_id = session.session_id
        if session_id in self._marked:
            self._marked.discard(session_id)
            marked = False
        else:
            self._marked.add(session_id)
            marked = True
        table = self.query_one("#sessions", DataTable)
        if self._mark_column is not None:
            table.update_cell(session_id, self._mark_column, self._marker(marked))
        self._render_summary()

    # -- delete --------------------------------------------------------------
    def action_delete_selected(self) -> None:
        """Delete the marked sessions, or the selected one."""
        base = 0
        if self._marked:
            marked = [s for s in self._all if s.session_id in self._marked]
            if not marked:
                return
            indices = [
                i for i, s in enumerate(self.sessions) if s.session_id in self._marked
            ]
            base = min(indices) if indices else 0
            self._restore_row = base
            self._confirm_bulk_delete(marked)
            return

        session = self._selected()
        if session is None:
            return
        table = self.query_one("#sessions", DataTable)
        self._restore_row = table.cursor_row
        self.app.push_screen(
            ChoiceScreen(
                f"Delete this session via 'opencode session delete'?\n\n"
                f"{session.title}\n{session.session_id}\n"
                f"Size (children included): {human_size(session.total_bytes)}",
                [("Delete", "yes"), ("Cancel", "no")],
                title="Delete session",
            ),
            lambda choice: self._on_delete(choice, session),
        )

    def _confirm_bulk_delete(self, targets: list[SessionSize]) -> None:
        """Prompt for confirmation before deleting marked sessions."""
        titles = "\n".join(f"• {s.title}" for s in targets[:8])
        if len(targets) > 8:
            titles += f"\n… +{len(targets) - 8} more"
        total = human_size(sum(s.total_bytes for s in targets))
        self.app.push_screen(
            ChoiceScreen(
                f"Delete {len(targets)} selected sessions via 'opencode session delete'?\n\n"
                f"{titles}\n\nTotal size (children included): {total}",
                [("Delete", "yes"), ("Cancel", "no")],
                title=f"Delete {len(targets)} sessions",
            ),
            self._on_bulk_delete,
        )

    def _on_bulk_delete(self, choice: str | None) -> None:
        """Delete the marked sessions when the choice is confirmed."""
        if choice != "yes":
            self._restore_row = None
            return
        targets = [s for s in self._all if s.session_id in self._marked]

        def work() -> list[tuple[SessionSize, bool, str]]:
            """Delete each marked session and collect results."""
            results: list[tuple[SessionSize, bool, str]] = []
            for session in targets:
                try:
                    result = delete_session(config, session.session_id, session.directory)
                    results.append((session, result.ok, result.stderr))
                except Exception as error:  # noqa: BLE001 - report per-session failure
                    results.append((session, False, str(error)))
            return results

        self.run_blocking(
            work,
            self._after_bulk_delete,
            message=f"Deleting {len(targets)} session(s)…",
        )

    def _after_bulk_delete(self, results: list[tuple[SessionSize, bool, str]]) -> None:
        """Report bulk delete results and reload the list."""
        self._marked.clear()
        ok = [r for r in results if r[1]]
        failed = [r for r in results if not r[1]]
        if failed:
            first = failed[0]
            self.app.notify(
                f"Deleted {len(ok)} session(s), {len(failed)} failed "
                f"(e.g. {escape(first[0].title)}: {escape(first[2].strip()[:120])})",
                severity="error",
                timeout=12,
            )
        else:
            self.app.notify(f"Deleted {len(ok)} session(s)", timeout=8)
        if not ok:
            self._restore_row = None
        self.reload()

    def _on_delete(self, choice: str | None, session: SessionSize) -> None:
        """Delete the session when the choice is confirmed."""
        if choice != "yes":
            self._restore_row = None
            return
        self.run_blocking(
            lambda: delete_session(config, session.session_id, session.directory),
            lambda result: self._after_delete(result, session),
        )

    def _after_delete(self, result: CliResult, session: SessionSize) -> None:
        """Report the delete result and reload the list."""
        if not result.ok:
            self.app.notify(f"Delete failed: {escape(result.stderr.strip())}", severity="error", timeout=10)
            self._restore_row = None
            return
        self.app.notify(f"Deleted: {escape(session.title)}", timeout=8)
        self.reload()

    # -- move ----------------------------------------------------------------
    def action_move_selected(self) -> None:
        """Prompt for a target directory to move the selected session to."""
        session = self._selected()
        if session is None:
            return
        self.app.push_screen(
            TextPromptScreen(
                "Move this session (and its children) to directory:",
                title="Move session",
                initial=str(Path(session.directory)) if session.directory else "",
            ),
            lambda value: self._on_move_target(value, session),
        )

    def _on_move_target(self, value: str | None, session: SessionSize) -> None:
        """Confirm the move to the entered target directory."""
        if not value:
            return
        target = Path(value.strip())
        self.app.push_screen(
            ChoiceScreen(
                f"Move session to:\n{target}\n\nCreate a backup first?",
                [("Move + backup", "move_backup"), ("Move", "move"), ("Cancel", "no")],
                title="Confirm move",
            ),
            lambda choice: self._on_move_choice(choice, session, target),
        )

    def _on_move_choice(self, choice: str | None, session: SessionSize, target: Path) -> None:
        """Move the session when the choice is confirmed."""
        if choice not in ("move", "move_backup"):
            return

        def work():
            """Optionally back up, then move the session."""
            if choice == "move_backup":
                create_backup(config)
            return move_session(config, session.session_id, target)

        self.run_blocking(work, self._after_move)

    def _after_move(self, result: MoveResult) -> None:
        """Report the move result and reload the list."""
        self.app.notify(
            f"Moved {result.moved_sessions} session(s) to {escape(str(result.to_directory))}", timeout=10
        )
        self.reload()

    # -- rename --------------------------------------------------------------
    def action_rename_selected(self) -> None:
        """Prompt for and apply a new title to the selected session."""
        session = self._selected()
        if session is None:
            return
        self.app.push_screen(
            TextPromptScreen("New title:", title="Rename session", initial=session.title),
            lambda value: self._on_rename(value, session),
        )

    def _on_rename(self, value: str | None, session: SessionSize) -> None:
        """Rename the session to the entered title."""
        title = (value or "").strip()
        if not title:
            return
        self.run_blocking(
            lambda: set_title(config, session.session_id, title),
            lambda _ok: self.reload(),
        )

    # -- export --------------------------------------------------------------
    def action_export_markdown(self) -> None:
        """Export the selected session as Markdown."""
        session = self._selected()
        if session is None:
            return
        dest = config.export_dir / f"{safe_filename(session.title, session.session_id)}.md"
        self._confirm_export(
            "Markdown",
            dest,
            lambda: export_markdown(config, session.session_id, dest, TranscriptOptions()),
        )

    def action_export_json(self) -> None:
        """Export the selected session as JSON."""
        session = self._selected()
        if session is None:
            return
        dest = config.export_dir / f"{safe_filename(session.title, session.session_id)}.json"
        self._confirm_export(
            "JSON",
            dest,
            lambda: export_json(config, session.session_id, dest, session.directory),
        )

    def _confirm_export(self, kind: str, dest: Path, work: Callable[[], Path]) -> None:
        """Prompt for confirmation before an export."""
        self.app.push_screen(
            ChoiceScreen(
                f"Export this session as {kind}?\n\n{dest}",
                [("Export", "yes"), ("Cancel", "no")],
                title=f"Export {kind}",
            ),
            lambda choice: self._on_export(choice, work),
        )

    def _on_export(self, choice: str | None, work: Callable[[], Path]) -> None:
        """Run the export when the choice is confirmed."""
        if choice != "yes":
            return
        self.run_blocking(work, self._notify_export, message="Exporting session…")

    def _notify_export(self, path: Path) -> None:
        """Report the exported file path."""
        self.app.notify(f"Exported: {escape(str(path))}", timeout=8)
