"""Read-only SQLite access to the OpenCode database.

All analytical queries run against a read-only connection so ocdu never
modifies the live database during inspection. Write operations (prune, VACUUM)
live in dedicated modules and open their own connection.
"""

from __future__ import annotations
import sqlite3
from contextlib import contextmanager
from collections.abc import Iterator
from pathlib import Path

# Tables that hold session-scoped payloads, used for size accounting.
_SESSION_PAYLOAD_TABLES = ("message", "part", "session_message", "todo")

# Cache of computed session sizes keyed by the database file state, so repeated
# screen loads do not rescan every blob. Invalidated when the db/WAL changes.
_SIZE_CACHE: dict[tuple, dict[str, dict[str, int]]] = {}

def _change_counter(db_path: Path) -> int:
    """Return the SQLite header change counter (bytes 24-27) or 0."""
    try:
        with open(db_path, "rb") as handle:
            header = handle.read(28)
    except OSError:
        return 0
    if len(header) >= 28:
        return int.from_bytes(header[24:28], "big")
    return 0

def _database_state(db_path: Path) -> tuple:
    """Return (mtime, size, change counter) tuples for the db, WAL and SHM files."""
    state = []
    for suffix in ("", "-wal", "-shm"):
        path = Path(str(db_path) + suffix)
        try:
            stat = path.stat()
            state.append((stat.st_mtime_ns, stat.st_size, _change_counter(path)))
        except OSError:
            state.append((0, 0, 0))
    return tuple(state)

def _readonly_uri(db_path: Path) -> str:
    """Return the ``mode=ro`` SQLite URI for a database file."""
    return db_path.resolve().as_uri() + "?mode=ro"

class Database:
    """Thin wrapper around the OpenCode SQLite database (read-only)."""

    def __init__(self, db_path: Path):
        """Store the path of the database to read."""
        self.db_path = db_path

    # -- connection ----------------------------------------------------------
    def connect(self) -> sqlite3.Connection:
        """Open a read-only connection with row access by name."""
        connection = sqlite3.connect(_readonly_uri(self.db_path), uri=True)
        connection.row_factory = sqlite3.Row
        return connection

    @contextmanager
    def open(self) -> Iterator[sqlite3.Connection]:
        """Open a read-only connection and close it on exit."""
        connection = self.connect()
        try:
            yield connection
        finally:
            connection.close()

    def exists(self) -> bool:
        """Return whether the database file exists."""
        return self.db_path.is_file()

    # -- pragmas -------------------------------------------------------------
    def pragma(self, connection: sqlite3.Connection, name: str):
        """Return the first column of a ``PRAGMA`` result."""
        row = connection.execute(f"PRAGMA {name}").fetchone()
        return row[0] if row else None

    def page_size(self, connection: sqlite3.Connection) -> int:
        """Return the database page size in bytes."""
        return int(self.pragma(connection, "page_size") or 4096)

    def freelist_count(self, connection: sqlite3.Connection) -> int:
        """Return the number of unused pages in the database."""
        return int(self.pragma(connection, "freelist_count") or 0)

    def integrity_check(self, connection: sqlite3.Connection) -> str:
        """Run ``PRAGMA integrity_check`` and return its text result."""
        row = connection.execute("PRAGMA integrity_check").fetchone()
        return row[0] if row else "unknown"

    # -- sizes ---------------------------------------------------------------
    def size_by_session(
        self, connection: sqlite3.Connection
    ) -> dict[str, dict[str, int]]:
        """Return ``{session_id: {table_name: payload_bytes}}``.

        ``event`` is keyed by ``aggregate_id`` (which equals the session id).
        Results are cached until the database file state changes.
        """
        key = _database_state(self.db_path)
        cached = _SIZE_CACHE.get(key)
        if cached is not None:
            return cached
        sizes = self._compute_size_by_session(connection)
        _SIZE_CACHE.clear()
        _SIZE_CACHE[key] = sizes
        return sizes

    def _compute_size_by_session(
        self, connection: sqlite3.Connection
    ) -> dict[str, dict[str, int]]:
        """Compute per-session payload sizes by table."""
        sizes: dict[str, dict[str, int]] = {}

        def bump(session_id: str, key: str, value: int) -> None:
            """Record a payload size for one session and table."""
            sizes.setdefault(session_id, {})[key] = value

        query = (
            "SELECT aggregate_id, SUM(length(cast(data AS blob))) "
            "FROM event GROUP BY aggregate_id"
        )
        for session_id, total in connection.execute(query):
            bump(session_id, "event", int(total or 0))

        for table in _SESSION_PAYLOAD_TABLES:
            column = "content" if table == "todo" else "data"
            query = (
                f"SELECT session_id, SUM(length(cast({column} AS blob))) "
                f"FROM {table} GROUP BY session_id"
            )
            for session_id, total in connection.execute(query):
                bump(session_id, table, int(total or 0))

        return sizes

    def size_by_directory(
        self, connection: sqlite3.Connection
    ) -> dict[str, int]:
        """Return ``{directory: total_bytes}`` across all session payloads."""
        per_session = self.size_by_session(connection)
        directory_by_session = {
            row["id"]: row["directory"]
            for row in connection.execute("SELECT id, directory FROM session")
        }
        totals: dict[str, int] = {}
        for session_id, parts in per_session.items():
            directory = directory_by_session.get(session_id)
            if directory is None:
                continue
            totals[directory] = totals.get(directory, 0) + sum(parts.values())
        return totals

    # -- orphans -------------------------------------------------------------
    def orphan_event_bytes(self, connection: sqlite3.Connection) -> tuple[int, int]:
        """Return ``(aggregate_count, event_bytes)`` for sessions that no longer exist."""
        query = (
            "SELECT COUNT(DISTINCT es.aggregate_id), "
            "COALESCE(SUM(length(cast(e.data AS blob))), 0) "
            "FROM event_sequence es "
            "LEFT JOIN event e ON e.aggregate_id = es.aggregate_id "
            "WHERE es.aggregate_id NOT IN (SELECT id FROM session)"
        )
        row = connection.execute(query).fetchone()
        if not row:
            return 0, 0
        return int(row[0] or 0), int(row[1] or 0)

    def session_ids(self, connection: sqlite3.Connection) -> set[str]:
        """Return the ids of all sessions."""
        return {row[0] for row in connection.execute("SELECT id FROM session")}

    # -- session metadata ----------------------------------------------------
    def session_rows(self, connection: sqlite3.Connection) -> list[dict]:
        """Return all sessions as dicts with their aggregate metadata."""
        query = (
            "SELECT id, parent_id, title, directory, time_updated, time_created, "
            "cost, tokens_input, tokens_output FROM session"
        )
        return [dict(row) for row in connection.execute(query)]

    def message_counts(self, connection: sqlite3.Connection) -> dict[str, int]:
        """Return the number of messages per session."""
        query = "SELECT session_id, COUNT(*) FROM message GROUP BY session_id"
        return {row[0]: int(row[1]) for row in connection.execute(query)}

    def root_session_ids(self, connection: sqlite3.Connection, directory: str) -> list[str]:
        """Return the root session ids that belong to one working directory."""
        query = "SELECT id FROM session WHERE parent_id IS NULL AND directory = ?"
        return [row[0] for row in connection.execute(query, (directory,))]
