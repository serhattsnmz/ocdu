"""Shared screen behavior for ocdu."""

from __future__ import annotations
import contextlib
from collections.abc import Callable
from typing import TypeVar
from textual.actions import SkipAction
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Static
from ...backup import create_backup
from ...cleanup import checkpoint, clean_logs, prune, vacuum
from ...config import config
from ...model import BackupResult, PruneResult, VacuumResult
from ...safety import probe
from ...util import human_size
from ..loading import LoadingOverlay
from ..table import CopyableDataTable
from .confirm import ChoiceScreen

T = TypeVar("T")

class OcduScreen(Screen):
    """Base screen: common navigation, reload and maintenance actions.

    The maintenance shortcuts (backup / prune / vacuum / checkpoint / logs) are
    defined here so they are available and visible on every screen.
    """

    BINDINGS = [
        Binding("q", "app.go_home", "Home"),
        Binding("escape", "app.go_home", show=False),
        Binding("backspace", "back", "Back"),
        Binding("r", "reload", "Reload"),
        Binding("p", "do_prune", "Prune"),
        Binding("v", "do_vacuum", "Vacuum"),
        Binding("ctrl+c", "copy_selection", show=False),
    ]

    def reload(self) -> None:
        """Reload data. Runs in a worker thread; override in subclasses."""

    def action_reload(self) -> None:
        """Reload the data shown on this screen."""
        self._announce_loading()
        self.reload()

    def action_copy_selection(self) -> None:
        """Copy the current text selection, then clear it.

        A second Ctrl+C (with nothing selected) falls through to the app's
        quit binding.
        """
        text = self.get_selected_text()
        if not text:
            raise SkipAction()
        self.app.copy_to_clipboard(text)
        self.clear_selection()

    def action_copy_row(self) -> None:
        """Copy the selected table row (all columns, tab-separated)."""
        table = self._active_table()
        if table is None:
            return
        text = table.row_text()
        if not text:
            return
        self.app.copy_to_clipboard(text)
        self.app.notify("Copied row to clipboard", timeout=3)

    def _active_table(self) -> CopyableDataTable | None:
        """Return the focused table, or the first table on the screen."""
        focused = self.focused
        if isinstance(focused, CopyableDataTable):
            return focused
        for table in self.query(CopyableDataTable):
            return table
        return None

    def action_back(self) -> None:
        """Return to the previous screen when possible."""
        if len(self.app.screen_stack) > 1:
            self.app.pop_screen()

    def _announce_loading(self) -> None:
        """Show a refreshing message in the summary panel, if present."""
        with contextlib.suppress(Exception):
            self.query_one("#summary", Static).update("Refreshing…")

    def run_blocking(
        self,
        work: Callable[[], T],
        on_done: Callable[[T], None],
        *,
        message: str | None = None,
    ) -> None:
        """Run ``work`` in a worker thread and deliver the result to ``on_done``.

        When ``message`` is given, a bottom-right loading overlay is shown for
        the duration of the operation (used for long-running tasks).
        """
        overlay: LoadingOverlay | None = None
        if message is not None:
            overlay = LoadingOverlay(message)
            self.mount(overlay)

        def close_overlay() -> None:
            """Remove the loading overlay when it is still mounted."""
            if overlay is not None and overlay.is_attached:
                overlay.remove()

        def finish(result: T) -> None:
            """Close the overlay and deliver the result."""
            close_overlay()
            on_done(result)

        def fail(error: Exception) -> None:
            """Close the overlay and report the failure."""
            close_overlay()
            self.app.notify(f"Operation failed: {error}", severity="error", timeout=10)

        def job() -> None:
            """Run the work function and marshal its outcome to the UI thread."""
            try:
                result = work()
            except Exception as error:  # noqa: BLE001 - surface any failure to the user
                self.app.call_from_thread(fail, error)
                return
            self.app.call_from_thread(finish, result)

        self.run_worker(job, thread=True)

    # -- maintenance actions (available on every screen) ---------------------
    def action_do_backup(self) -> None:
        """Prompt for and create a database backup."""
        self.app.push_screen(
            ChoiceScreen(
                f"Create a backup archive of the database?\nOnly the last "
                f"{config.backup_keep} archives are kept.",
                [("Create backup", "yes"), ("Cancel", "no")],
                title="Backup",
            ),
            self._on_backup,
        )

    def _on_backup(self, choice: str | None) -> None:
        """Handle the backup confirmation choice."""
        if choice != "yes":
            return
        self.run_blocking(
            lambda: create_backup(config), self._notify_backup, message="Creating backup…"
        )

    def _notify_backup(self, result: BackupResult) -> None:
        """Report the created backup and reload the screen."""
        self.app.notify(
            f"Backup created: {result.path.name} ({human_size(result.total_bytes)})", timeout=8
        )
        self.reload()

    def action_do_prune(self) -> None:
        """Prompt for and prune orphaned data."""
        self.app.push_screen(
            ChoiceScreen(
                "Remove provably-orphaned data and old log files?\n"
                f"Orphan events + session_diff files with no owning session are removed, "
                f"and logs older than {config.log_retention_days} days are deleted.",
                [("Prune + backup", "prune_backup"), ("Prune", "prune"), ("Cancel", "no")],
                title="Prune orphans",
            ),
            self._on_prune,
        )

    def _on_prune(self, choice: str | None) -> None:
        """Handle the prune confirmation choice."""
        if choice not in ("prune", "prune_backup"):
            return
        with_backup = choice == "prune_backup"
        self.run_blocking(
            lambda: self._prune_work(with_backup), self._notify_prune, message="Pruning…"
        )

    def _prune_work(self, with_backup: bool) -> tuple[PruneResult, tuple[int, int]]:
        """Prune orphans, checkpoint and clean logs off the UI thread."""
        result = prune(config, backup=with_backup)
        checkpoint(config)
        logs = clean_logs(config)
        return result, logs

    def _notify_prune(self, data: tuple[PruneResult, tuple[int, int]]) -> None:
        """Report the prune results and reload the screen."""
        result, (log_files, log_bytes) = data
        self.app.notify(
            f"Pruned: {result.orphan_event_sequences} event aggregates + "
            f"{result.session_diff_files} session_diff files "
            f"({human_size(result.freed_bytes)}). "
            f"Logs: {log_files} file(s), {human_size(log_bytes)}. "
            f"Run VACUUM to reclaim disk.",
            timeout=12,
        )
        self.reload()

    def action_do_vacuum(self) -> None:
        """Prompt for and run a database VACUUM."""
        self.app.push_screen(
            ChoiceScreen(
                "Run VACUUM to reclaim disk space? OpenCode should be closed.",
                [("Vacuum", "yes"), ("Cancel", "no")],
                title="VACUUM database",
            ),
            self._on_vacuum,
        )

    def _on_vacuum(self, choice: str | None) -> None:
        """Handle the vacuum confirmation choice."""
        if choice != "yes":
            return

        def work() -> VacuumResult:
            """Probe safety and run the VACUUM."""
            status = probe(config)
            if not status.safe_for_exclusive:
                raise RuntimeError(status.describe())
            return vacuum(config)

        self.run_blocking(work, self._notify_vacuum, message="Vacuuming…")

    def _notify_vacuum(self, result: VacuumResult) -> None:
        """Report the VACUUM result and reload the screen."""
        self.app.notify(
            f"VACUUM done: {human_size(result.before_bytes)} → "
            f"{human_size(result.after_bytes)} (saved {human_size(result.saved_bytes)})",
            timeout=10,
        )
        self.reload()
