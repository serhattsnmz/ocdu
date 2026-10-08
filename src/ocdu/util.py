"""Small shared helpers (size formatting, filesystem scanning)."""

from __future__ import annotations
import os
import re
from datetime import datetime
from pathlib import Path

_UNITS = ("B", "KB", "MB", "GB", "TB", "PB")
SECONDS_PER_DAY = 86_400
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
# Control characters that are safe to drop while keeping line breaks/tabs.
_LINE_CONTROL_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")

def human_size(num_bytes: int, precision: int = 1) -> str:
    """Format a byte count as a compact human-readable string."""
    size = float(num_bytes)
    for unit in _UNITS:
        if abs(size) < 1024.0 or unit == _UNITS[-1]:
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.{precision}f} {unit}"
        size /= 1024.0
    return f"{size:.{precision}f} {_UNITS[-1]}"

def dir_size(path: Path) -> tuple[int, int]:
    """Return ``(total_bytes, file_count)`` for a file or directory tree.

    Missing paths yield ``(0, 0)``. Unreadable entries are skipped.
    """
    try:
        if path.is_file():
            return path.stat().st_size, 1
        if not path.is_dir():
            return 0, 0
    except OSError:
        return 0, 0

    total = 0
    count = 0
    stack = [str(path)]
    while stack:
        current = stack.pop()
        try:
            with os.scandir(current) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        elif entry.is_file(follow_symlinks=False):
                            total += entry.stat(follow_symlinks=False).st_size
                            count += 1
                    except OSError:
                        continue
        except OSError:
            continue
    return total, count

def file_size(path: Path) -> int:
    """Return the size of a single file, or 0 if it does not exist."""
    try:
        return path.stat().st_size
    except OSError:
        return 0

def format_datetime(dt: datetime) -> str:
    """Format a datetime as the ocdu display format ``DD.MM.YYYY HH:MM``."""
    return dt.strftime("%d.%m.%Y %H:%M")

def format_time(epoch_ms: int | None) -> str:
    """Format a millisecond epoch timestamp as ``DD.MM.YYYY HH:MM``."""
    if not epoch_ms:
        return "-"
    try:
        return format_datetime(datetime.fromtimestamp(epoch_ms / 1000))
    except (OverflowError, OSError, ValueError):
        return "-"

def format_day(day: str) -> str:
    """Convert an ISO ``YYYY-MM-DD`` day to ``DD.MM.YYYY`` (passthrough on error)."""
    try:
        return datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return day

def strip_control(text: str) -> str:
    """Remove terminal control characters from untrusted text (titles, paths)."""
    return _CONTROL_RE.sub("", text)

def sanitize_text(text: str) -> str:
    """Remove control characters but keep line breaks and tabs (message bodies)."""
    return _LINE_CONTROL_RE.sub("", text)

def single_line(text: str) -> str:
    """Collapse all whitespace runs into single spaces (list previews)."""
    return " ".join(sanitize_text(text).split())
