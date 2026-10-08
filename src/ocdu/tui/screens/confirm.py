"""Reusable confirmation / choice modal."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Label, Static

class ChoiceScreen(ModalScreen[str | None]):
    """A modal that shows a message and a set of choices.

    Dismisses with the chosen option's key, or ``None`` if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "copy_or_cancel", show=False),
        Binding("backspace", "cancel", "Cancel", show=False),
        Binding("left", "focus_previous", "Previous", show=False),
        Binding("right", "focus_next", "Next", show=False),
    ]

    def __init__(
        self,
        message: str,
        options: list[tuple[str, str]],
        *,
        title: str = "Confirm",
    ) -> None:
        """Initialize the modal with its message and choices."""
        super().__init__()
        self.message = message
        self.options = options
        self.title_text = title

    def compose(self) -> ComposeResult:
        """Compose the dialog title, message and buttons."""
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            yield Static(self.message, id="dialog-message", markup=False)
            with Horizontal(id="dialog-buttons"):
                for label, key in self.options:
                    variant = "error" if key in ("yes", "prune", "prune_backup") else "default"
                    yield Button(label, id=key, variant=variant)

    def on_mount(self) -> None:
        """Focus the cancel button, or the last button when absent."""
        buttons = list(self.query(Button))
        if not buttons:
            return
        for button in buttons:
            if button.id in ("no", "cancel"):
                button.focus()
                return
        buttons[-1].focus()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss the modal with the pressed button's id."""
        self.dismiss(event.button.id)

    def action_focus_previous(self) -> None:
        """Move focus to the previous button."""
        self.focus_previous()

    def action_focus_next(self) -> None:
        """Move focus to the next button."""
        self.focus_next()

    def action_cancel(self) -> None:
        """Dismiss the modal without a choice."""
        self.dismiss(None)

    def action_copy_or_cancel(self) -> None:
        """Copy the current text selection, or cancel the dialog if empty."""
        text = self.get_selected_text()
        if text:
            self.app.copy_to_clipboard(text)
            self.clear_selection()
        else:
            self.action_cancel()
