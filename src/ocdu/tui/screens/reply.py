"""Reply: the pure assistant text that answers one user message."""

from __future__ import annotations
from rich.markup import escape
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import Screen
from textual.widgets import Footer, Header, Markdown, Static
from ...model import MessageTurn
from ...util import format_time, sanitize_text

_USER_BADGE = "[bold black on green] USER [/]"
_ASSISTANT_BADGE = "[bold black on cyan] ASSISTANT [/]"

class ReplyScreen(Screen):
    """Shows one user message and the flat assistant reply that follows it."""

    BINDINGS = [
        Binding("escape", "dismiss", "Back", show=False),
        Binding("backspace", "dismiss", "Back"),
        Binding("q", "dismiss", "Back", show=False),
    ]

    def __init__(self, turn: MessageTurn) -> None:
        """Store the conversation turn to display."""
        super().__init__()
        self.turn = turn

    def compose(self) -> ComposeResult:
        """Compose the user message and the assistant reply."""
        yield Header()
        with VerticalScroll(id="reply-scroll"):
            yield Static(self._user_title(), id="reply-user-title")
            yield Static(self._user_text(), id="reply-user")
            yield Static(_ASSISTANT_BADGE, id="reply-assistant-title")
            reply = sanitize_text(self.turn.reply_text)
            if reply:
                yield Markdown(reply, id="reply-assistant")
            else:
                yield Static("[dim](no response)[/]", id="reply-assistant")
        yield Footer()

    def _user_title(self) -> str:
        """Return the user badge with its timestamp."""
        stamp = escape(format_time(self.turn.user_time))
        return f"{_USER_BADGE}  [dim]{stamp}[/]"

    def _user_text(self) -> str:
        """Return the escaped user text, or a placeholder when empty."""
        text = sanitize_text(self.turn.user_text)
        return escape(text) if text else "[dim](attachment only)[/]"

    def action_dismiss(self) -> None:
        """Return to the previous screen."""
        self.app.pop_screen()
