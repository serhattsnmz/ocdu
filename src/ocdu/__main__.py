"""Command-line entry point for ocdu."""

from __future__ import annotations
import argparse
import contextlib
import ctypes
import sys
import time
from pathlib import Path
from . import __version__
from .analyze import directory_sizes, orphan_report, scan_roots, session_sizes
from .backup import backup_dir_size, create_backup, list_backups
from .cleanup import (
    checkpoint,
    clean_logs,
    integrity_check,
    prune,
    vacuum,
    vacuum_dry_run,
)
from .config import config
from .db import Database
from .export import TranscriptOptions, export_json, export_markdown, safe_filename
from .move import compute_path, descendants, move_session, resolve_target
from .opencode import delete_session
from .paths import build_roots
from .safety import probe
from .session_ops import set_title
from .stats import token_stats
from .util import format_day, human_size, strip_control

def _session_lookup(session_id: str) -> tuple[str, str, int] | None:
    """Return ``(title, directory, size_bytes)`` for a session, or None.

    ``size_bytes`` is the total a delete would remove, including every
    descendant (subagent) session.
    """
    db = Database(config.db_path)
    with db.open() as connection:
        row = connection.execute(
            "SELECT title, directory FROM session WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            return None
        sizes = db.size_by_session(connection)
        ids = [session_id, *descendants(connection, session_id)]
        total = sum(sum(sizes.get(sid, {}).values()) for sid in ids)
    return row["title"], row["directory"], total

def _print_orphan_summary(report) -> None:
    """Print the orphan breakdown shared by the ``orphans`` and ``prune`` commands."""
    print(
        f"  orphan event aggregates: {report.orphan_event_sequences}  "
        f"({human_size(report.orphan_event_bytes)})"
    )
    print(
        f"  orphan session_diff files: {len(report.orphan_session_diff_files)}  "
        f"({human_size(report.orphan_session_diff_bytes)})"
    )

# -- inspection --------------------------------------------------------------
def _cmd_footprint(_args: argparse.Namespace) -> int:
    """Print the size of every OpenCode data root."""
    report = scan_roots(build_roots(config))
    print("OpenCode data footprint")
    print(f"  data dir: {config.data_dir}\n")
    print(f"  {'CATEGORY':9} {'EXISTS':6} {'SIZE':>10}  {'FILES':>7}  LABEL")
    for entry in report.entries:
        print(
            f"  {entry.category:9} {'yes' if entry.exists else 'no':6}"
            f" {human_size(entry.size_bytes):>10}  {entry.file_count:>7}  {entry.label}"
        )
        print(f"  {'':9} {'':6} {'':>10}  {'':>7}  {entry.path}")
    print(f"\n  TOTAL: {human_size(report.total_bytes)}")
    return 0

def _cmd_build_dir(_args: argparse.Namespace) -> int:
    """Print the configured build output directory."""
    print(config.dist_dir)
    return 0

def _cmd_dirs(args: argparse.Namespace) -> int:
    """Print session data size grouped by directory."""
    db = Database(config.db_path)
    with db.open() as connection:
        sizes = directory_sizes(db, connection)
    ranked = sorted(sizes.items(), key=lambda item: item[1], reverse=True)
    shown = ranked if args.limit <= 0 else ranked[: args.limit]
    print("Session data by directory")
    for directory, total in shown:
        print(f"  {human_size(total):>10}  {directory}")
    print(f"\n  {len(ranked)} directories, total {human_size(sum(sizes.values()))}")
    return 0

def _cmd_sessions(args: argparse.Namespace) -> int:
    """Print per-session sizes with children aggregated by default."""
    db = Database(config.db_path)
    with db.open() as connection:
        sessions = session_sizes(db, connection, roots_only=not args.flat)
    ranked = sorted(sessions, key=lambda s: s.total_bytes, reverse=True)
    shown = ranked if args.limit <= 0 else ranked[: args.limit]
    scope = "all sessions (flat)" if args.flat else "root sessions (children aggregated)"
    print(f"Sessions — {scope}")
    print(f"  {'SIZE':>10}  {'MSG':>6}  {'CHILD':>5}  TITLE")
    for session in shown:
        print(
            f"  {human_size(session.total_bytes):>10}  {session.message_count:>6}"
            f"  {session.child_count:>5}  {strip_control(session.title)[:60]}"
        )
    total = sum(s.total_bytes for s in sessions)
    if len(shown) < len(ranked):
        print(f"\n  showing top {len(shown)} of {len(ranked)}; total {human_size(total)}")
    else:
        print(f"\n  {len(ranked)} sessions, total {human_size(total)}")
    return 0

def _cmd_orphans(_args: argparse.Namespace) -> int:
    """List provably-orphaned data that ocdu may clean."""
    db = Database(config.db_path)
    with db.open() as connection:
        report = orphan_report(db, connection, config)
    print("Orphans (provably safe to clean)")
    _print_orphan_summary(report)
    for file_path in report.orphan_session_diff_files[:20]:
        print(f"    - {file_path.name}")
    remaining = len(report.orphan_session_diff_files) - 20
    if remaining > 0:
        print(f"    ... and {remaining} more")
    print(f"  TOTAL orphan bytes: {human_size(report.total_bytes)}")
    return 0

# -- destructive / maintenance ----------------------------------------------
def _cmd_delete(args: argparse.Namespace) -> int:
    """Delete a session via the OpenCode CLI (dry-run unless ``--yes``)."""
    info = _session_lookup(args.session_id)
    if info is None:
        print(f"session not found: {args.session_id}", file=sys.stderr)
        return 2
    title, directory, size = info
    print(f"Session: {title}")
    print(f"  id:        {args.session_id}")
    print(f"  directory: {directory}")
    print(f"  size:      {human_size(size)} (everything a delete removes, children included)")

    if not args.yes:
        print("\nDry-run. Re-run with --yes to delete via 'opencode session delete'.")
        return 0

    result = delete_session(config, args.session_id, directory)
    if result.ok:
        print("\nDeleted. Run 'ocdu vacuum' to reclaim disk space.")
        return 0
    print(f"\nDelete failed (exit {result.returncode}):\n{result.stderr.strip()}", file=sys.stderr)
    return 1

def _cmd_prune(args: argparse.Namespace) -> int:
    """Remove provably-orphaned data (dry-run unless ``--yes``)."""
    db = Database(config.db_path)
    with db.open() as connection:
        report = orphan_report(db, connection, config)
    print("Orphan prune")
    _print_orphan_summary(report)
    print(f"  total: {human_size(report.total_bytes)}")

    if not args.yes:
        print("\nDry-run. Re-run with --yes to delete" + (" (with backup)" if args.backup else "") + ".")
        return 0

    if args.backup:
        backup = create_backup(config, extra_files=report.orphan_session_diff_files)
        print(f"\nBackup: {backup.path} ({human_size(backup.total_bytes)})")

    result = prune(config, backup=False)
    print(
        f"\nPruned: {result.orphan_event_sequences} event aggregates "
        f"({human_size(result.orphan_event_bytes)}), "
        f"{result.session_diff_files} session_diff files "
        f"({human_size(result.session_diff_bytes)})."
    )
    print(f"  freed (logical): {human_size(result.freed_bytes)}")
    print("  Run 'ocdu vacuum' to reclaim disk space.")
    return 0

def _cmd_vacuum(args: argparse.Namespace) -> int:
    """Checkpoint and VACUUM the database (dry-run unless ``--yes``)."""
    dry = vacuum_dry_run(config)
    print("Database VACUUM")
    print(f"  current size:       {human_size(dry.before_bytes)}")
    print(f"  reclaimable (free): {human_size(dry.saved_bytes)}")

    if not args.yes:
        print("\nDry-run. Re-run with --yes to VACUUM.")
        return 0

    status = probe(config)
    if not status.safe_for_exclusive and not args.force:
        print(f"\nRefusing: {status.describe()}. Close OpenCode or pass --force.", file=sys.stderr)
        return 1

    result = vacuum(config)
    print(f"\n  before: {human_size(result.before_bytes)}")
    print(f"  after:  {human_size(result.after_bytes)}")
    print(f"  saved:  {human_size(result.saved_bytes)}")
    return 0

def _cmd_backup(_args: argparse.Namespace) -> int:
    """Create a database backup archive and rotate old ones."""
    result = create_backup(config)
    print(f"Backup created: {result.path}")
    print(f"  db snapshot: {human_size(result.db_bytes)}")
    print(f"  archive:     {human_size(result.total_bytes)}")
    if result.removed_old:
        print(f"  rotated out: {len(result.removed_old)} old archive(s)")
    archives = list_backups(config)
    print(f"  {len(archives)} archive(s), total {human_size(backup_dir_size(config))} in {config.backup_dir}")
    return 0

def _cmd_check(_args: argparse.Namespace) -> int:
    """Run the database integrity check and environment probe."""
    print(f"integrity_check: {integrity_check(config)}")
    status = probe(config)
    print(f"environment: {status.describe()}")
    return 0

def _cmd_move(args: argparse.Namespace) -> int:
    """Move a session and its children to another directory."""
    info = _session_lookup(args.session_id)
    if info is None:
        print(f"session not found: {args.session_id}", file=sys.stderr)
        return 2
    title, current, size = info
    target = Path(args.directory)
    project = resolve_target(target)
    new_path = compute_path(project.worktree, str(project.directory))

    print(f"Session: {title}")
    print(f"  id:          {args.session_id}")
    print(f"  size:        {human_size(size)}")
    print(f"  from:        {current}")
    print(f"  to:          {project.directory.as_posix()}")
    print(f"  project id:  {project.project_id}")
    print(f"  session path:{' ' + new_path if new_path else ' (root)'}")

    if not project.directory.is_dir() and not args.force:
        print("\nTarget directory does not exist. Create it or pass --force.", file=sys.stderr)
        return 1

    if not args.yes:
        print("\nDry-run. Re-run with --yes to move" + (" (with backup)" if args.backup else "") + ".")
        return 0

    if args.backup:
        backup = create_backup(config)
        print(f"\nBackup: {backup.path} ({human_size(backup.total_bytes)})")

    result = move_session(config, args.session_id, target, force=args.force)
    print(f"\nMoved {result.moved_sessions} session(s) to {result.to_directory}")
    return 0

def _cmd_rename(args: argparse.Namespace) -> int:
    """Rename a session title."""
    if not set_title(config, args.session_id, args.title):
        print(f"session not found: {args.session_id}", file=sys.stderr)
        return 2
    print(f"Renamed: {args.session_id} -> {args.title}")
    return 0

def _cmd_stats(_args: argparse.Namespace) -> int:
    """Print token and cost statistics."""
    db = Database(config.db_path)
    with db.open() as connection:
        report = token_stats(db, connection)
    totals = report.totals
    print("Token & cost statistics")
    print(f"  sessions:     {totals.sessions}")
    print(f"  tokens in:    {totals.tokens_input:,}")
    print(f"  tokens out:   {totals.tokens_output:,}")
    print(f"  total cost:   ${totals.cost:,.2f}")
    print("\n  By model (top 10):")
    for stat in report.by_model[:10]:
        label = f"{strip_control(stat.provider)}/{strip_control(stat.model)}"
        print(f"    ${stat.cost:>9.2f}  {stat.sessions:>5} ses  {label}")
    print("\n  By directory (top 10):")
    for stat in report.by_directory[:10]:
        print(f"    ${stat.cost:>9.2f}  {stat.sessions:>5} ses  {strip_control(stat.directory)}")
    print("\n  By day (last 10):")
    for stat in report.by_day[:10]:
        print(f"    {format_day(stat.day)}  {stat.sessions:>5} ses  ${stat.cost:>8.2f}")
    return 0

def _cmd_clean_logs(args: argparse.Namespace) -> int:
    """Delete old log files (dry-run unless ``--yes``)."""
    if args.days is not None and args.days < 0:
        print("--days must be >= 0", file=sys.stderr)
        return 2
    days = args.days if args.days is not None else config.log_retention_days
    count, total = clean_logs(config, days, dry_run=True)
    print(f"Log cleanup (> {days} days): {count} file(s), {human_size(total)}")
    if not args.yes:
        print("\nDry-run. Re-run with --yes to delete.")
        return 0
    removed, freed = clean_logs(config, days)
    print(f"Deleted {removed} file(s), freed {human_size(freed)}.")
    return 0

def _cmd_checkpoint(_args: argparse.Namespace) -> int:
    """Checkpoint the WAL without a full VACUUM."""
    result = checkpoint(config)
    print(f"WAL checkpoint: {human_size(result.before_bytes)} -> {human_size(result.after_bytes)} "
          f"(saved {human_size(result.saved_bytes)})")
    return 0

# -- export ------------------------------------------------------------------
def _resolve_dest(args: argparse.Namespace, title: str, session_id: str, ext: str) -> Path:
    """Return the export destination file path."""
    if args.out:
        out = Path(args.out)
        if out.is_dir():
            return out / f"{safe_filename(title, session_id)}.{ext}"
        return out
    return Path.cwd() / f"{safe_filename(title, session_id)}.{ext}"

def _cmd_export(args: argparse.Namespace) -> int:
    """Export a session as a JSON or Markdown file."""
    info = _session_lookup(args.session_id)
    if info is None:
        print(f"session not found: {args.session_id}", file=sys.stderr)
        return 2
    title, directory, _size = info

    if args.format == "json":
        dest = _resolve_dest(args, title, args.session_id, "json")
        path = export_json(config, args.session_id, dest, directory)
    else:
        options = TranscriptOptions(
            thinking=args.thinking,
            tool_details=not args.no_tool_details,
            assistant_metadata=not args.no_metadata,
        )
        dest = _resolve_dest(args, title, args.session_id, "md")
        path = export_markdown(config, args.session_id, dest, options)
    print(f"Exported: {path}")
    return 0

def _use_utf8_output() -> None:
    """Make console output UTF-8 so titles with non-Latin characters don't crash."""
    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetConsoleOutputCP(65001)
            ctypes.windll.kernel32.SetConsoleCP(65001)
        except (AttributeError, OSError):
            pass
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="replace")

def _build_parser() -> argparse.ArgumentParser:
    """Build the command-line argument parser with every subcommand."""
    parser = argparse.ArgumentParser(prog="ocdu", description="OpenCode disk usage")
    parser.add_argument("--version", action="version", version=f"ocdu {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("tui", help="launch the interactive dashboard (default)")
    _add_inspection_commands(sub)
    _add_maintenance_commands(sub)
    _add_session_commands(sub)
    return parser

def _add_inspection_commands(sub: argparse._SubParsersAction) -> None:
    """Register the read-only inspection subcommands."""
    sub.add_parser("footprint", help="show size of every OpenCode data root")
    sub.add_parser("build-dir", help="print the configured build output directory")

    p_dirs = sub.add_parser("dirs", help="session data size by directory")
    p_dirs.add_argument("-n", "--limit", type=int, default=0, help="max rows (0 = all)")

    p_sessions = sub.add_parser("sessions", help="session sizes (children included)")
    p_sessions.add_argument("-n", "--limit", type=int, default=0, help="max rows (0 = all)")
    p_sessions.add_argument("--flat", action="store_true",
                            help="list every session individually instead of aggregating children")

    sub.add_parser("orphans", help="list provably-orphaned data")

def _add_maintenance_commands(sub: argparse._SubParsersAction) -> None:
    """Register the database maintenance subcommands."""
    p_prune = sub.add_parser("prune", help="remove provably-orphaned data")
    p_prune.add_argument("-y", "--yes", action="store_true", help="actually delete (else dry-run)")
    p_prune.add_argument("-b", "--backup", action="store_true", help="create a backup before pruning")

    p_vacuum = sub.add_parser("vacuum", help="checkpoint + VACUUM the database")
    p_vacuum.add_argument("-y", "--yes", action="store_true", help="actually run (else dry-run)")
    p_vacuum.add_argument("-f", "--force", action="store_true",
                          help="run even if OpenCode appears to be running")

    sub.add_parser("backup", help="create a database backup archive (keep last N)")
    sub.add_parser("check", help="run integrity check and environment probe")
    sub.add_parser("checkpoint", help="checkpoint the WAL (no full VACUUM)")
    sub.add_parser("stats", help="token and cost statistics")

    p_logs = sub.add_parser("clean-logs", help="delete old log files")
    p_logs.add_argument("-d", "--days", type=int, default=None,
                        help="age threshold in days (default: LOG_RETENTION_DAYS)")
    p_logs.add_argument("-y", "--yes", action="store_true", help="actually delete (else dry-run)")

def _add_session_commands(sub: argparse._SubParsersAction) -> None:
    """Register the per-session subcommands."""
    p_delete = sub.add_parser("delete", help="delete a session via the OpenCode CLI")
    p_delete.add_argument("session_id")
    p_delete.add_argument("-y", "--yes", action="store_true", help="actually delete (else dry-run)")

    p_move = sub.add_parser("move", help="move a session (and children) to another directory")
    p_move.add_argument("session_id")
    p_move.add_argument("directory")
    p_move.add_argument("-y", "--yes", action="store_true", help="actually move (else dry-run)")
    p_move.add_argument("-b", "--backup", action="store_true", help="create a backup before moving")
    p_move.add_argument("-f", "--force", action="store_true", help="allow a missing target directory")

    p_rename = sub.add_parser("rename", help="rename a session title")
    p_rename.add_argument("session_id")
    p_rename.add_argument("title")

    p_export = sub.add_parser("export", help="export a session as JSON or Markdown")
    p_export.add_argument("session_id")
    p_export.add_argument("-o", "--out", help="output file or directory (default: current dir)")
    p_export.add_argument("-f", "--format", choices=["md", "json"], default="md")
    p_export.add_argument("--thinking", action="store_true", help="include reasoning text (md)")
    p_export.add_argument("--no-tool-details", action="store_true", help="omit tool input/output (md)")
    p_export.add_argument("--no-metadata", action="store_true", help="omit assistant metadata (md)")

def main(argv: list[str] | None = None) -> int:
    """Run the requested CLI subcommand (or launch the TUI by default)."""
    _use_utf8_output()
    parser = _build_parser()
    args = parser.parse_args(argv)
    command = args.command or "tui"

    if command == "tui":
        # Imported lazily so CLI-only commands never pay the Textual import cost.
        from .tui.app import run

        run()
        return 0

    if command not in ("footprint", "build-dir") and not config.db_path.is_file():
        print(f"database not found: {config.db_path}", file=sys.stderr)
        return 2

    started = time.perf_counter()
    handlers = {
        "footprint": _cmd_footprint,
        "build-dir": _cmd_build_dir,
        "dirs": _cmd_dirs,
        "sessions": _cmd_sessions,
        "orphans": _cmd_orphans,
        "delete": _cmd_delete,
        "prune": _cmd_prune,
        "vacuum": _cmd_vacuum,
        "backup": _cmd_backup,
        "check": _cmd_check,
        "checkpoint": _cmd_checkpoint,
        "stats": _cmd_stats,
        "move": _cmd_move,
        "rename": _cmd_rename,
        "clean-logs": _cmd_clean_logs,
        "export": _cmd_export,
    }
    result = handlers[command](args)
    if command not in ("footprint", "backup", "build-dir"):
        print(f"\n({time.perf_counter() - started:.2f}s)")
    return result

if __name__ == "__main__":
    raise SystemExit(main())
