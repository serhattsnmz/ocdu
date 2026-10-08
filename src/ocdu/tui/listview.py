"""ListView that selects on a single click and activates on a double click.

Textual's stock ``ListView`` posts ``Selected`` on any click. These widgets keep
the cursor behaviour (single click highlights, double click or Enter activates),
mirroring the row tables.
"""

from __future__ import annotations
from textual import events
from textual.binding import Binding
from textual.widgets import ListItem, ListView

class ClickSelectItem(ListItem):
    """A ``ListItem`` that remembers the click chain for its parent list."""

    last_chain = 1

    def _on_click(self, event: events.Click) -> None:
        """Record the click chain and forward a child-clicked message."""
        self.last_chain = event.chain
        self.post_message(self._ChildClicked(self))
        # Textual dispatches ``_on_click`` for every class in the MRO; stop the
        # base ListItem handler from posting a second message.
        event._no_default_action = True

class ClickSelectListView(ListView):
    """Single click highlights an item; double click activates it.

    ``end`` / ``home`` move the *selection* to the last / first item (the stock
    ``ListView`` binds them to viewport scrolling).
    """

    BINDINGS = [
        Binding("end", "select_last", "End", show=False),
        Binding("home", "select_first", "Home", show=False),
    ]

    def _on_list_item__child_clicked(self, event: ListItem._ChildClicked) -> None:
        """Select the clicked item and activate it only on a double click."""
        event.stop()
        # The base ListView handler posts ``Selected`` on any click; suppress it
        # so only a double click activates the item.
        event._no_default_action = True
        self.focus()
        self.index = self._nodes.index(event.item)
        if getattr(event.item, "last_chain", 1) == 2:
            self.post_message(self.Selected(self, event.item, self.index))

    def action_select_last(self) -> None:
        """Move the selection to the last item."""
        if len(self):
            self.index = len(self) - 1

    def action_select_first(self) -> None:
        """Move the selection to the first item."""
        if len(self):
            self.index = 0
