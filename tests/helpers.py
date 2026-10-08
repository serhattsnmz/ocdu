"""Small filesystem and SQLite helpers shared by the ocdu tests."""

from __future__ import annotations
import os
import time
from pathlib import Path

def insert(conn, table: str, row: dict) -> None:
    """Insert a single ``row`` dict into ``table`` using its column names."""
    columns = ", ".join(row)
    placeholders = ", ".join("?" for _ in row)
    conn.execute(f"INSERT INTO {table} ({columns}) VALUES ({placeholders})", tuple(row.values()))

def write_file(path: Path, content: str = "x") -> Path:
    """Write ``content`` to ``path`` (creating parents) and return the path."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path

def make_file(path: Path, size: int = 0) -> Path:
    """Create a file of ``size`` bytes (filled with ``b'x'``) and return it."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path

def age_file(path: Path, days: float) -> Path:
    """Backdate a file's mtime by ``days`` and return the path."""
    stamp = time.time() - days * 86_400
    os.utime(path, (stamp, stamp))
    return path
