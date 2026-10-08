"""Inspection and size analysis of OpenCode data."""

from __future__ import annotations
import sqlite3
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from .config import Config, config as default_config
from .db import Database
from .model import (
    DirectorySummary,
    OrphanReport,
    RootEntry,
    ScanReport,
    SessionSize,
)
from .util import dir_size, file_size

# -- filesystem footprint ----------------------------------------------------
def scan_root(entry: RootEntry) -> RootEntry:
    """Populate size/exists info for a single root and return it."""
    total = 0
    count = 0
    exists = False
    for path in entry.all_paths:
        if path.exists():
            exists = True
        size, files = dir_size(path)
        total += size
        count += files
    entry.exists = exists
    entry.size_bytes = total
    entry.file_count = count
    return entry

def scan_roots(
    roots: list[RootEntry],
    report: ScanReport | None = None,
    on_entry: Callable[[RootEntry], None] | None = None,
) -> ScanReport:
    """Populate size/exists info for every root and return the report.

    Roots are scanned concurrently; ``on_entry`` (if given) is called for each
    root as soon as its scan finishes, so callers can render progressively.
    """
    report = report or ScanReport()
    report.entries = roots
    if not roots:
        return report
    with ThreadPoolExecutor(max_workers=min(8, len(roots))) as pool:
        futures = [pool.submit(scan_root, entry) for entry in roots]
        for future in as_completed(futures):
            entry = future.result()
            if on_entry is not None:
                on_entry(entry)
    return report

# -- database sizing ---------------------------------------------------------
def _load_session_maps(
    db: Database, connection: sqlite3.Connection
) -> tuple[dict[str, dict], dict[str, list[str]]]:
    """Return session rows by id and a parent-to-children map."""
    rows = db.session_rows(connection)
    by_id = {row["id"]: row for row in rows}
    children: dict[str, list[str]] = {}
    for row in rows:
        parent = row["parent_id"]
        if parent:
            children.setdefault(parent, []).append(row["id"])
    return by_id, children

def _own_session_size(row: dict, parts: dict, message_count: int) -> SessionSize:
    """Build the size record for a single session without its children."""
    return SessionSize(
        session_id=row["id"],
        title=row["title"],
        directory=row["directory"],
        is_root=row["parent_id"] is None,
        message_count=message_count,
        child_count=0,
        event_bytes=parts.get("event", 0),
        message_bytes=parts.get("message", 0),
        part_bytes=parts.get("part", 0),
        session_message_bytes=parts.get("session_message", 0),
        todo_bytes=parts.get("todo", 0),
        time_updated=int(row["time_updated"] or 0),
        tokens_input=int(row.get("tokens_input") or 0),
        tokens_output=int(row.get("tokens_output") or 0),
        cost=float(row.get("cost") or 0.0),
    )

def _merge_session_sizes(base: SessionSize, extra: SessionSize) -> None:
    """Fold ``extra`` (children already merged) into ``base`` in place."""
    base.event_bytes += extra.event_bytes
    base.message_bytes += extra.message_bytes
    base.part_bytes += extra.part_bytes
    base.session_message_bytes += extra.session_message_bytes
    base.todo_bytes += extra.todo_bytes
    base.message_count += extra.message_count
    base.child_count += 1 + extra.child_count
    base.tokens_input += extra.tokens_input
    base.tokens_output += extra.tokens_output
    base.cost += extra.cost

def _aggregate_session(
    session_id: str,
    by_id: dict[str, dict],
    children: dict[str, list[str]],
    per_session: dict[str, dict],
    message_counts: dict[str, int],
) -> SessionSize:
    """Return a session with all descendant sizes folded in."""
    row = by_id[session_id]
    result = _own_session_size(row, per_session.get(session_id, {}), message_counts.get(session_id, 0))
    for child_id in children.get(session_id, []):
        _merge_session_sizes(result, _aggregate_session(child_id, by_id, children, per_session, message_counts))
    return result

def session_sizes(
    db: Database,
    connection: sqlite3.Connection,
    *,
    roots_only: bool = True,
) -> list[SessionSize]:
    """Return per-session sizes.

    When ``roots_only`` is true, each entry aggregates the session together with
    all of its descendant (subagent) sessions, mirroring what a session delete
    removes.
    """
    by_id, children = _load_session_maps(db, connection)
    per_session = db.size_by_session(connection)
    message_counts = db.message_counts(connection)

    if roots_only:
        targets = [sid for sid, row in by_id.items() if row["parent_id"] is None]
        return [_aggregate_session(sid, by_id, children, per_session, message_counts) for sid in targets]

    sessions = [
        _own_session_size(row, per_session.get(sid, {}), message_counts.get(sid, 0))
        for sid, row in by_id.items()
    ]
    for session in sessions:
        session.child_count = len(children.get(session.session_id, []))
    return sessions

def directory_sizes(
    db: Database, connection: sqlite3.Connection
) -> dict[str, int]:
    """Return ``{directory: total_bytes}`` for all session payloads."""
    return db.size_by_directory(connection)

def directory_summaries(
    db: Database, connection: sqlite3.Connection
) -> list[DirectorySummary]:
    """Return per-directory summaries sorted by size (largest first)."""
    sizes = db.size_by_directory(connection)
    summaries: dict[str, DirectorySummary] = {}
    for row in db.session_rows(connection):
        directory = row["directory"]
        summary = summaries.get(directory)
        if summary is None:
            summary = DirectorySummary(
                directory=directory,
                size_bytes=sizes.get(directory, 0),
                session_count=0,
                root_count=0,
                last_updated=0,
                exists=bool(directory) and Path(directory).is_dir(),
            )
            summaries[directory] = summary
        summary.session_count += 1
        if row["parent_id"] is None:
            summary.root_count += 1
        summary.last_updated = max(summary.last_updated, int(row["time_updated"] or 0))
    return sorted(summaries.values(), key=lambda s: s.size_bytes, reverse=True)

# -- orphans -----------------------------------------------------------------
def orphan_report(
    db: Database,
    connection: sqlite3.Connection,
    config: Config = default_config,
) -> OrphanReport:
    """Detect provably-orphaned data that ocdu may clean."""
    report = OrphanReport()
    report.orphan_event_sequences, report.orphan_event_bytes = (
        db.orphan_event_bytes(connection)
    )

    diff_dir = config.data_dir / "storage" / "session_diff"
    if diff_dir.is_dir():
        known = db.session_ids(connection)
        for file_path in sorted(diff_dir.glob("*.json")):
            session_id = file_path.stem
            if session_id not in known:
                report.orphan_session_diff_files.append(file_path)
                report.orphan_session_diff_bytes += file_size(file_path)

    return report
