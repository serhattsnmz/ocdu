"""Backups: consistent database snapshot + touched files, as a single archive.

Flow: take a consistent snapshot of the live database (SQLite online backup
API, WAL-safe), VACUUM the snapshot to make it compact, then store the snapshot
together with any extra files in one zip. Only the newest ``BACKUP_KEEP``
archives are retained.
"""

from __future__ import annotations
import os
import sqlite3
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path
from .config import Config
from .model import BackupResult
from .util import dir_size, file_size

_ARCHIVE_PREFIX = "ocdu-backup-"
_DB_ARCNAME = "opencode.db"

def _snapshot_database(src: Path, dest: Path) -> int:
    """Write a consistent, vacuumed copy of ``src`` to ``dest``. Returns size."""
    source = sqlite3.connect(src.resolve().as_uri() + "?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(dest))
        try:
            source.backup(target)
            target.execute("VACUUM")
            target.commit()
        finally:
            target.close()
    finally:
        source.close()
    return file_size(dest)

def create_backup(config: Config, extra_files: list[Path] | None = None) -> BackupResult:
    """Create a single backup archive and rotate old ones."""
    backup_dir = config.backup_dir
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    archive_path = backup_dir / f"{_ARCHIVE_PREFIX}{timestamp}.zip"
    counter = 1
    while archive_path.exists():
        archive_path = backup_dir / f"{_ARCHIVE_PREFIX}{timestamp}-{counter}.zip"
        counter += 1

    extra_files = [path for path in (extra_files or []) if path.is_file()]

    with tempfile.TemporaryDirectory(prefix="ocdu-backup-") as temp_dir:
        temp_path = Path(temp_dir)
        db_bytes = 0
        db_snapshot: Path | None = None
        if config.db_path.is_file():
            db_snapshot = temp_path / _DB_ARCNAME
            db_bytes = _snapshot_database(config.db_path, db_snapshot)

        temp_archive = archive_path.with_name(archive_path.name + ".part")
        try:
            with zipfile.ZipFile(temp_archive, "w", zipfile.ZIP_DEFLATED) as archive:
                if db_snapshot is not None and db_snapshot.is_file():
                    archive.write(db_snapshot, _DB_ARCNAME)
                for file_path in extra_files:
                    archive.write(file_path, f"extra/{file_path.name}")
            os.replace(temp_archive, archive_path)
        except BaseException:
            temp_archive.unlink(missing_ok=True)
            raise

    total_bytes = file_size(archive_path)
    removed = rotate_backups(config)
    return BackupResult(
        path=archive_path,
        db_bytes=db_bytes,
        total_bytes=total_bytes,
        extra_files=len(extra_files),
        removed_old=removed,
    )

def list_backups(config: Config) -> list[Path]:
    """Return backup archives, newest first."""
    backup_dir = config.backup_dir
    if not backup_dir.is_dir():
        return []
    archives = sorted(
        backup_dir.glob(f"{_ARCHIVE_PREFIX}*.zip"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    return archives

def rotate_backups(config: Config) -> list[Path]:
    """Delete archives beyond ``BACKUP_KEEP`` (newest kept). Returns removed."""
    archives = list_backups(config)
    removed: list[Path] = []
    for archive in archives[config.backup_keep :]:
        try:
            archive.unlink()
            removed.append(archive)
        except OSError:
            continue
    return removed

def backup_dir_size(config: Config) -> int:
    """Total size of the backup directory in bytes."""
    return dir_size(config.backup_dir)[0]
