"""Theme picker modal with live preview and persistence."""

from __future__ import annotations
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList, Static
from textual.widgets.option_list import Option
from ...config import save_ui_overrides

class ThemePickerScreen(ModalScreen[str | None]):
    """Pick a theme, previewing it live while the cursor moves.

    ``Enter`` applies and persists the theme; ``Escape``/``Backspace`` restores
    the theme that was active when the picker opened.
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
        Binding("ctrl+c", "copy_or_cancel", show=False),
        Binding("backspace", "cancel", "Cancel", show=False),
    ]

    def __init__(self) -> None:
        """Initialize the picker with no remembered theme."""
        super().__init__()
        self._original = ""

    def compose(self) -> ComposeResult:
        """Compose the dialog title, hint and theme list."""
        with Vertical(id="dialog"):
            yield Label("Theme", id="dialog-title")
            yield Static(
                "Use ↑/↓ to preview, Enter to apply, Esc to cancel.",
                id="dialog-message",
            )
            yield OptionList(id="theme-list")

    def on_mount(self) -> None:
        """Populate the theme list and highlight the active theme."""
        self._original = self.app.theme
        option_list = self.query_one("#theme-list", OptionList)
        names = sorted(
            name for name in self.app.available_themes if not name.startswith("ansi")
        )
        for name in names:
            option_list.add_option(Option(name, id=name))
        if self._original in names:
            option_list.highlighted = names.index(self._original)
        option_list.focus()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Preview the highlighted theme without persisting it."""
        if event.option.id:
            self.app.theme = event.option.id

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Apply, persist and dismiss with the selected theme."""
        if event.option.id:
            self.app.theme = event.option.id
            save_ui_overrides({"THEME": event.option.id})
        self.dismiss(event.option.id)

    def action_cancel(self) -> None:
        """Restore the original theme and dismiss without a choice."""
        if self._original:
            self.app.theme = self._original
        self.dismiss(None)

    def action_copy_or_cancel(self) -> None:
        """Copy the current text selection, or cancel the dialog if empty."""
        text = self.get_selected_text()
        if text:
            self.app.copy_to_clipboard(text)
            self.clear_selection()
        else:
            self.action_cancel()
