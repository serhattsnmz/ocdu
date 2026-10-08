"""Reusable single-line text prompt modal."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label

class TextPromptScreen(ModalScreen[str | None]):
    """Ask the user for a single line of text.

    Dismisses with the entered string, or ``None`` if cancelled.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "copy_or_cancel", show=False),
        Binding("backspace", "cancel", "Cancel", show=False),
        Binding("left", "focus_previous", "Previous", show=False),
        Binding("right", "focus_next", "Next", show=False),
    ]

    def __init__(self, message: str, *, title: str = "Input", initial: str = "") -> None:
        """Initialize the modal with its message, title and initial value."""
        super().__init__()
        self.message = message
        self.title_text = title
        self.initial = initial

    def compose(self) -> ComposeResult:
        """Compose the dialog title, message, input and buttons."""
        with Vertical(id="dialog"):
            yield Label(self.title_text, id="dialog-title")
            yield Label(self.message, id="dialog-message")
            yield Input(value=self.initial, id="dialog-input")
            with Horizontal(id="dialog-buttons"):
                yield Button("OK", id="ok", variant="primary")
                yield Button("Cancel", id="cancel")

    def on_mount(self) -> None:
        """Focus the text input."""
        self.query_one("#dialog-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Dismiss the modal with the submitted text."""
        self.dismiss(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Dismiss with the input value on OK, or ``None`` on cancel."""
        if event.button.id == "ok":
            self.dismiss(self.query_one("#dialog-input", Input).value)
        else:
            self.dismiss(None)

    def action_focus_previous(self) -> None:
        """Move focus to the previous widget."""
        self.focus_previous()

    def action_focus_next(self) -> None:
        """Move focus to the next widget."""
        self.focus_next()

    def action_cancel(self) -> None:
        """Dismiss the modal without a value."""
        self.dismiss(None)

    def action_copy_or_cancel(self) -> None:
        """Copy the current text selection, or cancel the dialog if empty."""
        text = self.get_selected_text()
        if text:
            self.app.copy_to_clipboard(text)
            self.clear_selection()
        else:
            self.action_cancel()
