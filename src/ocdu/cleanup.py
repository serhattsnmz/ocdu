"""Cleanup: safe orphan removal, VACUUM and integrity checks."""

from __future__ import annotations
import sqlite3
import time
from pathlib import Path
from .analyze import orphan_report
from .backup import create_backup
from .config import Config
from .db import Database
from .model import PruneResult, VacuumResult
from .util import SECONDS_PER_DAY, file_size

def _db_total(config: Config) -> int:
    """Total size of the database file plus its WAL/SHM companions."""
    base = config.db_path
    return (
        file_size(base)
        + file_size(Path(str(base) + "-wal"))
        + file_size(Path(str(base) + "-shm"))
    )

def _connect_rw(config: Config) -> sqlite3.Connection:
    """Open a writable connection with foreign keys enabled."""
    if not config.db_path.is_file():
        raise FileNotFoundError(f"database not found: {config.db_path}")
    connection = sqlite3.connect(str(config.db_path), timeout=30.0)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection

def delete_orphan_events(config: Config) -> tuple[int, int]:
    """Delete event rows for sessions that no longer exist.

    Returns ``(aggregate_count, freed_bytes)``. Deleting the ``event_sequence``
    row cascades to ``event`` via the foreign key.
    """
    connection = _connect_rw(config)
    try:
        cursor = connection.execute(
            "SELECT COUNT(*), COALESCE(SUM((SELECT COALESCE(SUM(length(cast(e.data AS blob))),0) "
            "FROM event e WHERE e.aggregate_id = es.aggregate_id)),0) "
            "FROM event_sequence es WHERE es.aggregate_id NOT IN (SELECT id FROM session)"
        )
        row = cursor.fetchone()
        count = int(row[0] or 0)
        freed = int(row[1] or 0)
        if count:
            connection.execute(
                "DELETE FROM event WHERE aggregate_id NOT IN (SELECT id FROM session)"
            )
            connection.execute(
                "DELETE FROM event_sequence WHERE aggregate_id NOT IN (SELECT id FROM session)"
            )
            connection.commit()
        return count, freed
    finally:
        connection.close()

def delete_orphan_session_diff(files: list[Path]) -> tuple[int, int]:
    """Delete orphaned ``session_diff`` files. Returns ``(count, freed_bytes)``."""
    removed = 0
    freed = 0
    for file_path in files:
        size = file_size(file_path)
        try:
            file_path.unlink()
            removed += 1
            freed += size
        except OSError:
            continue
    return removed, freed

def prune(
    config: Config,
    *,
    do_events: bool = True,
    do_session_diff: bool = True,
    backup: bool = False,
) -> PruneResult:
    """Remove provably-orphaned data, optionally backing up first."""
    db = Database(config.db_path)
    with db.open() as connection:
        report = orphan_report(db, connection, config)

    if backup:
        create_backup(config, extra_files=report.orphan_session_diff_files)

    result = PruneResult()
    if do_events:
        result.orphan_event_sequences, result.orphan_event_bytes = delete_orphan_events(config)
    if do_session_diff:
        result.session_diff_files, result.session_diff_bytes = delete_orphan_session_diff(
            report.orphan_session_diff_files
        )
    return result

def vacuum(config: Config) -> VacuumResult:
    """Checkpoint the WAL and VACUUM the database to reclaim disk space."""
    before = _db_total(config)
    connection = _connect_rw(config)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        connection.execute("VACUUM")
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    return VacuumResult(before_bytes=before, after_bytes=_db_total(config))

def vacuum_dry_run(config: Config) -> VacuumResult:
    """Report the current size and the reclaimable free pages without writing."""
    db = Database(config.db_path)
    with db.open() as connection:
        page_size = db.page_size(connection)
        freelist = db.freelist_count(connection)
    current = _db_total(config)
    reclaimable = page_size * freelist
    return VacuumResult(before_bytes=current, after_bytes=max(0, current - reclaimable))

def integrity_check(config: Config) -> str:
    """Run ``PRAGMA integrity_check`` on the database."""
    db = Database(config.db_path)
    with db.open() as connection:
        return db.integrity_check(connection)

def checkpoint(config: Config) -> VacuumResult:
    """Checkpoint the WAL (truncate) without a full VACUUM."""
    before = _db_total(config)
    connection = _connect_rw(config)
    try:
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        connection.close()
    return VacuumResult(before_bytes=before, after_bytes=_db_total(config))

def clean_logs(
    config: Config,
    older_than_days: int | None = None,
    *,
    dry_run: bool = False,
) -> tuple[int, int]:
    """Delete (or preview, with ``dry_run``) log files older than a threshold.

    Returns ``(count, freed_bytes)``.
    """
    days = config.log_retention_days if older_than_days is None else older_than_days
    cutoff = time.time() - max(0, days) * SECONDS_PER_DAY
    log_dir = config.data_dir / "log"
    removed = 0
    freed = 0
    if not log_dir.is_dir():
        return 0, 0
    for file_path in log_dir.glob("*"):
        try:
            if not file_path.is_file() or file_path.stat().st_mtime >= cutoff:
                continue
            size = file_path.stat().st_size
            if not dry_run:
                file_path.unlink()
            removed += 1
            freed += size
        except OSError:
            continue
    return removed, freed
