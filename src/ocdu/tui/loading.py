"""A bottom-right loading overlay for long-running operations."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.widgets import LoadingIndicator, Static

class LoadingOverlay(Container):
    """A transient spinner with a message, floating at the bottom-right.

    It is rendered in the built-in ``_loading`` layer so it does not disturb the
    screen layout while a background operation runs.
    """

    DEFAULT_CSS = """
    LoadingOverlay {
        layer: _loading;
        dock: bottom;
        width: 1fr;
        height: auto;
        align-horizontal: right;
        margin-bottom: 1;
    }
    LoadingOverlay #loading-box {
        width: auto;
        height: auto;
        padding: 0 1;
        background: $panel;
        border: round $accent;
        align-vertical: middle;
    }
    LoadingOverlay #loading-box LoadingIndicator {
        width: 1;
        height: 1;
    }
    LoadingOverlay #loading-message {
        width: auto;
        padding: 0 1;
    }
    """

    def __init__(self, message: str) -> None:
        """Store the message shown next to the spinner."""
        super().__init__()
        self.message = message

    def compose(self) -> ComposeResult:
        """Yield the spinner and its message."""
        with Horizontal(id="loading-box"):
            yield LoadingIndicator()
            yield Static(self.message, id="loading-message", markup=False)
