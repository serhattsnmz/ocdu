"""Textual application entry point."""

from __future__ import annotations
from collections.abc import Iterable
from textual.app import App, Screen, SystemCommand
from textual.binding import Binding
from textual.command import DiscoveryHit, Hits
from textual.system_commands import SystemCommandsProvider
from rich.markup import escape
from ..config import config, save_ui_overrides
from .screens.browse import BrowseScreen
from .screens.dashboard import DashboardScreen
from .screens.keys import KeysScreen
from .screens.stats import StatsScreen
from .screens.theme import ThemePickerScreen

APP_CSS = """
Screen {
    background: $surface;
}
DataTable {
    height: 1fr;
}
#summary {
    padding: 1 2;
    background: transparent;
    border: round $accent;
    color: $text;
}
#detail {
    padding: 1 2;
    height: auto;
}
#messages-title {
    padding: 0 2;
    color: $text-muted;
}
#messages {
    height: 1fr;
    padding: 0 1;
}
#messages ListItem {
    height: auto;
    padding: 0 1;
    margin: 0 0 1 0;
}
#messages Label {
    width: 1fr;
}
#reply-scroll {
    height: 1fr;
}
#reply-user-title {
    padding: 1 2 0 2;
}
#reply-user {
    margin: 0 2;
    padding: 0 2;
    background: $boost;
    border-left: thick $accent;
}
#reply-assistant-title {
    padding: 1 2 0 2;
}
#reply-assistant {
    padding: 0 2 1 2;
    margin: 0 2;
    border-left: thick cyan;
}
ChoiceScreen, TextPromptScreen, ThemePickerScreen, KeysScreen {
    align: center middle;
    background: transparent;
}
KeysScreen #dialog {
    width: 80;
    height: 80%;
}
KeysScreen KeyPanel {
    width: 1fr;
    height: 1fr;
    min-width: 0;
    max-width: 100%;
    border: none;
    split: none;
    padding: 0;
}
#dialog {
    width: 72;
    height: auto;
    padding: 1 2;
    background: $panel;
    border: round $accent;
}
ThemePickerScreen #dialog {
    width: 50;
    max-height: 70%;
    background: $panel 85%;
}
#dialog-title {
    text-style: bold;
    padding-bottom: 1;
}
#dialog-message {
    padding-bottom: 1;
}
#dialog-buttons {
    height: auto;
    align-horizontal: right;
}
#dialog-buttons Button {
    margin-left: 2;
    background: $surface;
    color: $text;
    border: none;
    border-top: tall $surface-lighten-1;
    border-bottom: tall $surface-darken-1;
}
#dialog-buttons Button:hover {
    background: $surface-lighten-1;
}
#dialog-buttons Button:focus {
    background: $primary;
    color: $text;
    border: none;
    border-top: tall $primary-lighten-1;
    border-bottom: tall $primary-darken-1;
}
ThemePickerScreen #theme-list {
    height: auto;
    max-height: 100%;
}
CommandPalette {
    align: center middle;
    background: transparent;
}
CommandPalette > Vertical {
    margin-top: 0;
    height: auto;
    max-height: 70%;
    width: 70%;
    visibility: visible;
    background: $panel;
    border: round $accent;
    padding: 0 1;
}
CommandPalette #--input {
    height: auto;
    border: none;
    border-bottom: solid $border-blurred;
}
CommandPalette #--input.--list-visible {
    border-bottom: solid $border-blurred;
}
CommandPalette #--results {
    overlay: none;
    height: auto;
}
CommandPalette CommandList {
    height: auto;
    max-height: 100%;
}
"""

class OcduSystemCommandsProvider(SystemCommandsProvider):
    """System commands provider that keeps the order defined by the app.

    The stock provider sorts discovery commands alphabetically; we want Theme
    first and Quit last, so we yield ``get_system_commands`` verbatim.
    """

    async def discover(self) -> Hits:
        """Yield the app's system commands in their defined order."""
        for name, help_text, callback, discover in self.app.get_system_commands(self.screen):
            if discover:
                yield DiscoveryHit(name, callback, help=help_text)

class OcduApp(App):
    """ncdu-style browser for OpenCode data."""

    TITLE = "ocdu"
    SUB_TITLE = "OpenCode disk usage"
    CSS = APP_CSS
    COMMANDS = (OcduSystemCommandsProvider,)
    BINDINGS = [
        Binding("ctrl+c", "quit", "Copy / Quit", show=True),
        Binding("alt+left", "navigate_back", "Back", show=False),
    ]
    _persist_theme_enabled = True

    def get_default_screen(self) -> Screen:
        """Return the initial browse screen."""
        return BrowseScreen()

    def on_mount(self) -> None:
        """Apply the saved theme and persist future theme changes."""
        theme = config.theme
        if theme in self.available_themes and not theme.startswith("ansi"):
            self.theme = theme
        self.theme_changed_signal.subscribe(self, self._persist_theme)

    def _persist_theme(self, theme) -> None:
        """Persist the name of the newly selected theme (unless suppressed).

        The active theme picker suppresses persistence so previewing with the
        cursor never writes the config file; the picker saves explicitly on
        selection instead.
        """
        if isinstance(self.screen, ThemePickerScreen) or not self._persist_theme_enabled:
            return
        name = getattr(theme, "name", "")
        if name:
            save_ui_overrides({"THEME": name})

    def set_theme_persistence(self, enabled: bool) -> None:
        """Enable or disable persisting theme changes.

        The theme picker disables this while previewing so moving the cursor does
        not write the config file; it re-enables it before applying a choice.
        """
        self._persist_theme_enabled = enabled

    # -- back navigation -----------------------------------------------------
    def action_navigate_back(self) -> None:
        """Go back on Alt+Left (mirrors Backspace)."""
        screen = self.screen
        for name in ("action_back", "action_dismiss", "action_cancel"):
            action = getattr(screen, name, None)
            if callable(action):
                action()
                return

    # -- command palette -----------------------------------------------------
    def get_system_commands(self, screen: Screen) -> Iterable[SystemCommand]:
        """Yield the system commands shown in the command palette."""
        yield SystemCommand("Theme", "Change the current theme", self.action_open_theme_picker)
        yield SystemCommand(
            "Token Stats", "Token and cost statistics", self.action_show_token_stats
        )
        yield SystemCommand(
            "Disk Stats", "Disk usage of every OpenCode data root", self.action_show_disk_stats
        )
        yield SystemCommand(
            "Database Backup",
            "Create a backup archive of the database",
            self.action_database_backup,
        )
        if screen.query("CopyableDataTable"):
            yield SystemCommand(
                "Copy selected row",
                "Copy the selected table row to the clipboard",
                screen.action_copy_row,
            )
        summary = self._summary_widget(screen)
        if summary is not None:
            if summary.display:
                yield SystemCommand(
                    "Hide info panel",
                    "Hide the info panel to enlarge the table",
                    self.action_hide_info_panel,
                )
            else:
                yield SystemCommand(
                    "Show info panel", "Show the info panel", self.action_show_info_panel
                )
        for command in super().get_system_commands(screen):
            if command.title in ("Theme", "Quit", "Keys", "Maximize", "Minimize", "Screenshot"):
                continue
            yield command
        yield SystemCommand("Screenshot", "Save an SVG screenshot", self.action_save_screenshot)
        yield SystemCommand(
            "Show Keys",
            "Show the key bindings for the current screen",
            lambda: self.push_screen(KeysScreen(screen)),
        )
        yield SystemCommand("Quit", "Quit the application as soon as possible", self.action_quit)

    # -- info panel ----------------------------------------------------------
    def _summary_widget(self, screen: Screen):
        """Return the info-panel widget, or ``None`` when absent."""
        for widget in screen.query("#summary"):
            return widget
        return None

    def _set_info_panel(self, visible: bool) -> None:
        """Show or hide the info panel."""
        summary = self._summary_widget(self.screen)
        if summary is not None:
            summary.display = visible

    def action_show_info_panel(self) -> None:
        """Show the info panel."""
        self._set_info_panel(True)

    def action_hide_info_panel(self) -> None:
        """Hide the info panel."""
        self._set_info_panel(False)

    # -- theme ---------------------------------------------------------------
    def action_open_theme_picker(self) -> None:
        """Open the theme picker screen."""
        self.push_screen(ThemePickerScreen())

    # -- screenshot ----------------------------------------------------------
    def action_save_screenshot(self) -> None:
        """Schedule saving an SVG screenshot."""
        self.set_timer(0.1, self._save_screenshot)

    def _save_screenshot(self) -> None:
        """Save an SVG screenshot to the screenshot directory."""
        directory = config.screenshot_dir
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = self.save_screenshot(path=str(directory))
        except OSError as error:
            self.notify(f"Screenshot failed: {escape(str(error))}", severity="error", timeout=10)
            return
        self.notify(f"Screenshot saved: {escape(str(path))}", timeout=8)

    # -- stats screens -------------------------------------------------------
    def action_show_token_stats(self) -> None:
        """Open the token statistics screen."""
        self.push_screen(StatsScreen())

    def action_show_disk_stats(self) -> None:
        """Open the disk usage dashboard screen."""
        self.push_screen(DashboardScreen())

    def action_database_backup(self) -> None:
        """Trigger a backup on the active screen when supported."""
        action = getattr(self.screen, "action_do_backup", None)
        if callable(action):
            action()

    # -- navigation ----------------------------------------------------------
    async def action_go_home(self) -> None:
        """Pop every screen until the default screen is reached."""
        while len(self.screen_stack) > 1:
            await self.pop_screen()

def run() -> None:
    """Launch the ocdu Textual application."""
    OcduApp().run()
