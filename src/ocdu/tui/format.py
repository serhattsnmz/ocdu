"""Formatting helpers for TUI cells: alignment, size colors, home shortening."""

from __future__ import annotations
from pathlib import Path
from rich.text import Text
from ..util import human_size

SIZE_WIDTH = 9
COUNT_WIDTH = 8
COST_WIDTH = 9
TOKEN_WIDTH = 12

_GB = 1024**3
_MB = 1024**2

def header_text(label: str, width: int) -> Text:
    """Right-aligned column header (to sit above right-aligned numbers)."""
    return Text(label.rjust(width))

def size_text(num_bytes: int, width: int = SIZE_WIDTH) -> Text:
    """Human-readable size, right-aligned; red for GB+, yellow for MB."""
    text = Text(human_size(num_bytes).rjust(width))
    if num_bytes >= _GB:
        text.stylize("red")
    elif num_bytes >= _MB:
        text.stylize("yellow")
    return text

def count_text(value: int, width: int = COUNT_WIDTH) -> Text:
    """Right-aligned count cell."""
    return Text(str(value).rjust(width))

def cost_text(value: float, width: int = COST_WIDTH) -> Text:
    """Right-aligned cost cell formatted as US dollars."""
    return Text(f"${value:,.2f}".rjust(width))

def token_text(value: int, width: int = TOKEN_WIDTH) -> Text:
    """Right-aligned token count with thousands separators."""
    return Text(f"{value:,}".rjust(width))

def size_markup(num_bytes: int) -> str:
    """Markup string for a size (used outside of DataTable cells)."""
    label = human_size(num_bytes)
    if num_bytes >= _GB:
        return f"[red]{label}[/]"
    if num_bytes >= _MB:
        return f"[yellow]{label}[/]"
    return label

def shorten_home(path: str | Path) -> str:
    """Replace a leading home-directory prefix with ``~``."""
    raw = str(path)
    normalized = raw.replace("\\", "/")
    home = str(Path.home()).replace("\\", "/").rstrip("/")
    if not home:
        return raw
    lowered = normalized.lower()
    home_lowered = home.lower()
    if lowered == home_lowered:
        return "~"
    if lowered.startswith(home_lowered + "/"):
        return "~/" + normalized[len(home) + 1 :]
    return raw
