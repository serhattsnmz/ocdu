"""Modal that shows the active key bindings of the screen it opened from."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import ActiveBinding, Binding
from textual.containers import Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import KeyPanel, Label

class KeysScreen(ModalScreen[None]):
    """A modal listing the key bindings of the originating screen.

    ``KeyPanel`` renders ``self.screen.active_bindings``; inside this modal that
    would be the modal's own bindings, so we delegate to the source screen.
    """

    BINDINGS = [
        Binding("escape", "close", "Close", show=False),
        Binding("backspace", "close", "Close", show=False),
    ]

    def __init__(self, source: Screen) -> None:
        """Store the screen whose bindings should be listed."""
        super().__init__()
        self._source = source

    @property
    def active_bindings(self) -> dict[str, ActiveBinding]:
        """Return the active bindings of the originating screen."""
        return self._source.active_bindings

    def compose(self) -> ComposeResult:
        """Compose the dialog title and key panel."""
        with Vertical(id="dialog"):
            yield Label("Key bindings", id="dialog-title")
            yield KeyPanel()

    def action_close(self) -> None:
        """Close the modal."""
        self.dismiss(None)
