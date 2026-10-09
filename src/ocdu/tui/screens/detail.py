"""Detail: size breakdown of a single session."""

from __future__ import annotations
from collections.abc import Callable
from pathlib import Path
from textual.app import ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Label, ListView, Static
from rich.markup import escape
from ...analyze import session_sizes
from ...backup import create_backup
from ...config import config
from ...conversation import conversation_turns
from ...db import Database
from ...export import TranscriptOptions, export_json, export_markdown, safe_filename
from ...model import MessageTurn, SessionSize
from ...move import MoveResult, move_session
from ...opencode import CliResult, delete_session
from ...safety import opencode_processes
from ...session_ops import set_title
from ...state import pinned_session_ids, toggle_pinned
from ...util import format_time, human_size, single_line
from ..format import shorten_home, size_markup
from ..listview import ClickSelectItem, ClickSelectListView
from .base import OcduScreen
from .confirm import ChoiceScreen
from .prompt import TextPromptScreen
from .reply import ReplyScreen

class DetailScreen(OcduScreen):
    """Shows the size breakdown of a session (everything a delete would remove)."""

    BINDINGS = OcduScreen.BINDINGS + [
        Binding("d", "delete_session", "Delete"),
        Binding("m", "move_session", "Move"),
        Binding("n", "rename_session", "Rename"),
        Binding("f", "toggle_pin", "Pin"),
        Binding("e", "export_markdown", "Export MD"),
        Binding("j", "export_json", "Export JSON"),
        Binding("o", "toggle_message_sort", "Sort msgs"),
    ]

    def __init__(self, session: SessionSize) -> None:
        """Store the session to display and its message ordering."""
        super().__init__()
        self.session = session
        self._turns: list[MessageTurn] = []
        self._ordered: list[MessageTurn] = []
        self._msg_desc = True
        self._pinned = session.session_id in pinned_session_ids(config)

    def compose(self) -> ComposeResult:
        """Compose the header, size breakdown and message list."""
        yield Header()
        yield Static(self._build_text(), id="detail")
        yield Static("Messages (user)", id="messages-title")
        yield ClickSelectListView(id="messages")
        yield Footer()

    def on_mount(self) -> None:
        """Load the conversation when the screen mounts."""
        self.reload_conversation()

    def reload(self) -> None:
        """Reload the session size breakdown."""
        self.run_blocking(self._load, self._on_reload)

    def _load(self) -> SessionSize | None:
        """Load the current size record for this session."""
        db = Database(config.db_path)
        with db.open() as connection:
            sessions = session_sizes(db, connection, roots_only=True)
        target = self.session.session_id
        for session in sessions:
            if session.session_id == target:
                return session
        return None

    def _on_reload(self, session: SessionSize | None) -> None:
        """Apply a reloaded size record, or leave when it vanished."""
        if session is None:
            self.app.notify("Session no longer exists.", severity="warning", timeout=8)
            self.app.pop_screen()
            return
        self.session = session
        self.query_one("#detail", Static).update(self._build_text())

    # -- conversation --------------------------------------------------------
    def reload_conversation(self) -> None:
        """Reload the session's conversation turns."""
        self.run_blocking(self._load_conversation, self._set_conversation)

    def _load_conversation(self) -> list[MessageTurn]:
        """Load the conversation turns from the database."""
        db = Database(config.db_path)
        with db.open() as connection:
            return conversation_turns(connection, self.session.session_id)

    def _set_conversation(self, turns: list[MessageTurn]) -> None:
        """Store the loaded turns and populate the message list."""
        self._turns = turns
        self._populate_messages()

    def _populate_messages(self) -> None:
        """Rebuild the message list in the current sort order."""
        self._ordered = sorted(
            self._turns, key=lambda t: (t.user_time, t.user_id), reverse=self._msg_desc
        )
        list_view = self.query_one("#messages", ListView)
        list_view.clear()
        items = []
        for turn in self._ordered:
            text = single_line(turn.user_text) or "(attachment only)"
            label = Label(f"[dim]{escape(format_time(turn.user_time))}[/]  {escape(text)}")
            items.append(ClickSelectItem(label))
        if items:
            list_view.extend(items)
        order = "newest first" if self._msg_desc else "oldest first"
        self.query_one("#messages-title", Static).update(
            f"User messages — {len(self._ordered)} — {order}"
        )

        def focus_first() -> None:
            """Focus the first message after the refresh."""
            if self._ordered:
                list_view.index = 0
                list_view.focus()

        self.call_after_refresh(focus_first)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Open the selected message's reply screen."""
        if 0 <= event.index < len(self._ordered):
            self.app.push_screen(ReplyScreen(self._ordered[event.index]))

    def action_toggle_message_sort(self) -> None:
        """Toggle the message sort order."""
        self._msg_desc = not self._msg_desc
        self._populate_messages()

    def action_toggle_pin(self) -> None:
        """Toggle the pinned state of this session."""
        session_id = self.session.session_id
        try:
            self._pinned = toggle_pinned(config, session_id)
        except OSError as error:
            self.app.notify(f"Pin update failed: {escape(str(error))}", severity="error", timeout=10)
            return
        self.query_one("#detail", Static).update(self._build_text())
        self.run_blocking(opencode_processes, self._warn_if_running)

    def _warn_if_running(self, processes: list[str]) -> None:
        """Warn that a live OpenCode instance may overwrite the pin change."""
        if processes:
            self.app.notify(
                "OpenCode appears to be running; it may overwrite this change.",
                severity="warning",
                timeout=10,
            )

    def _build_text(self) -> str:
        """Render the session metadata and size breakdown as text."""
        s = self.session
        rows = [
            ("Title", escape(f"★ {s.title}" if self._pinned else s.title)),
            ("Session ID", escape(s.session_id)),
            ("Directory", escape(shorten_home(s.directory))),
            ("Root session", "yes" if s.is_root else "no"),
            ("Updated", format_time(s.time_updated)),
            ("Messages", str(s.message_count)),
            ("Child sessions", str(s.child_count)),
            ("Tokens in / out", f"{s.tokens_input:,} / {s.tokens_output:,}"),
            ("Cost", f"${s.cost:.2f}"),
            ("", ""),
            ("event", size_markup(s.event_bytes)),
            ("message", size_markup(s.message_bytes)),
            ("part", size_markup(s.part_bytes)),
            ("session_message", size_markup(s.session_message_bytes)),
            ("todo", size_markup(s.todo_bytes)),
            ("", ""),
            ("TOTAL (delete removes)", f"[bold]{size_markup(s.total_bytes)}[/]"),
        ]
        width = max(len(label) for label, _ in rows)
        return "\n".join(f"{label.ljust(width)}  {value}" for label, value in rows)

    # -- actions -------------------------------------------------------------
    def action_delete_session(self) -> None:
        """Prompt for and delete this session."""
        s = self.session
        self.app.push_screen(
            ChoiceScreen(
                f"Delete this session via 'opencode session delete'?\n\n"
                f"{s.title}\n{s.session_id}\n"
                f"Size (children included): {human_size(s.total_bytes)}",
                [("Delete", "yes"), ("Cancel", "no")],
                title="Delete session",
            ),
            self._on_delete,
        )

    def _on_delete(self, choice: str | None) -> None:
        """Delete the session when the choice is confirmed."""
        if choice != "yes":
            return
        session = self.session
        self.run_blocking(
            lambda: delete_session(config, session.session_id, session.directory),
            self._after_delete,
        )

    def _after_delete(self, result: CliResult) -> None:
        """Report the delete result and return to the previous screen."""
        if not result.ok:
            self.app.notify(f"Delete failed: {escape(result.stderr.strip())}", severity="error", timeout=10)
            return
        self.app.notify(f"Deleted: {escape(self.session.title)}", timeout=8)
        self.app.pop_screen()
        target = self.app.screen
        reload = getattr(target, "reload", None)
        if callable(reload):
            reload()

    def action_export_markdown(self) -> None:
        """Export this session as Markdown."""
        s = self.session
        dest = config.export_dir / f"{safe_filename(s.title, s.session_id)}.md"
        self._confirm_export(
            "Markdown",
            dest,
            lambda: export_markdown(config, s.session_id, dest, TranscriptOptions()),
        )

    def action_export_json(self) -> None:
        """Export this session as JSON."""
        s = self.session
        dest = config.export_dir / f"{safe_filename(s.title, s.session_id)}.json"
        self._confirm_export(
            "JSON",
            dest,
            lambda: export_json(config, s.session_id, dest, s.directory),
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

    # -- move / rename -------------------------------------------------------
    def action_move_session(self) -> None:
        """Prompt for a target directory to move this session to."""
        self.app.push_screen(
            TextPromptScreen(
                "Move this session (and its children) to directory:",
                title="Move session",
                initial=str(Path(self.session.directory)) if self.session.directory else "",
            ),
            self._on_move_target,
        )

    def _on_move_target(self, value: str | None) -> None:
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
            lambda choice: self._on_move_choice(choice, target),
        )

    def _on_move_choice(self, choice: str | None, target: Path) -> None:
        """Move the session when the choice is confirmed."""
        if choice not in ("move", "move_backup"):
            return

        session = self.session

        def work():
            """Optionally back up, then move the session."""
            if choice == "move_backup":
                create_backup(config)
            return move_session(config, session.session_id, target)

        self.run_blocking(work, self._after_move)

    def _after_move(self, result: MoveResult) -> None:
        """Report the move result and return to the previous screen."""
        self.app.notify(
            f"Moved {result.moved_sessions} session(s) to {escape(str(result.to_directory))}", timeout=10
        )
        self.app.pop_screen()
        target = self.app.screen
        reload = getattr(target, "reload", None)
        if callable(reload):
            reload()

    def action_rename_session(self) -> None:
        """Prompt for and apply a new session title."""
        self.app.push_screen(
            TextPromptScreen("New title:", title="Rename session", initial=self.session.title),
            self._on_rename,
        )

    def _on_rename(self, value: str | None) -> None:
        """Rename the session to the entered title."""
        title = (value or "").strip()
        if not title:
            return
        session = self.session
        self.run_blocking(
            lambda: set_title(config, session.session_id, title),
            self._after_rename,
        )

    def _after_rename(self, _ok: bool) -> None:
        """Report the rename and return to the previous screen."""
        self.app.notify("Session renamed.", timeout=8)
        self.app.pop_screen()
        target = self.app.screen
        reload = getattr(target, "reload", None)
        if callable(reload):
            reload()
