"""Session metadata operations: rename."""

from __future__ import annotations
import sqlite3
import time
from .config import Config

def _connect(config: Config) -> sqlite3.Connection:
    """Open a writable connection with foreign keys enabled."""
    connection = sqlite3.connect(str(config.db_path), timeout=30.0)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def set_title(config: Config, session_id: str, title: str) -> bool:
    """Rename a session. Returns True if the session existed.

    Raises ``ValueError`` when ``title`` is empty or only whitespace, so the
    database never ends up with a blank session title.
    """
    title = title.strip()
    if not title:
        raise ValueError("title must not be empty")
    connection = _connect(config)
    try:
        cursor = connection.execute(
            "UPDATE session SET title = ?, time_updated = ? WHERE id = ?",
            (title, int(time.time() * 1000), session_id),
        )
        connection.commit()
        return cursor.rowcount > 0
    finally:
        connection.close()
