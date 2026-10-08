"""Build the map of every OpenCode data location tracked by ocdu."""

from __future__ import annotations
from pathlib import Path
from .config import Config, config as default_config
from .model import (
    CATEGORY_BACKUP,
    CATEGORY_INFO,
    CATEGORY_LOCKED,
    CATEGORY_MANAGED,
    RootEntry,
)

def build_roots(config: Config = default_config) -> list[RootEntry]:
    """Return the ordered list of tracked data roots."""
    return _managed_roots(config) + _info_roots(config) + _locked_roots(config)

def _managed_roots(config: Config) -> list[RootEntry]:
    """Roots ocdu may clean or operate on directly."""
    data_dir = config.data_dir
    db_path = config.db_path

    return [
        RootEntry(
            key="database",
            label="Database",
            path=db_path,
            companions=[
                Path(str(db_path) + "-wal"),
                Path(str(db_path) + "-shm"),
            ],
            category=CATEGORY_MANAGED,
            note="SQLite, WAL mode; sessions/messages/events",
        ),
        RootEntry(
            key="session_diff",
            label="Session diffs",
            path=data_dir / "storage" / "session_diff",
            category=CATEGORY_MANAGED,
            note="orphaned when a session is deleted",
        ),
        RootEntry(
            key="backups",
            label="Backups",
            path=config.backup_dir,
            category=CATEGORY_BACKUP,
            note=f"ocdu archives (keep {config.backup_keep})",
        ),
        RootEntry(
            key="log",
            label="Log files",
            path=data_dir / "log",
            category=CATEGORY_MANAGED,
            note="no automatic cleanup",
        ),
    ]

def _info_roots(config: Config) -> list[RootEntry]:
    """Roots shown for information; OpenCode manages them itself."""
    data_dir = config.data_dir

    return [
        RootEntry(
            key="snapshot",
            label="Snapshots",
            path=data_dir / "snapshot",
            category=CATEGORY_INFO,
            note="per-project git snapshots (gc 7d)",
        ),
        RootEntry(
            key="tool_output",
            label="Tool output",
            path=data_dir / "tool-output",
            category=CATEGORY_INFO,
            note="truncation cache (7-day retention)",
        ),
        RootEntry(
            key="repos",
            label="Repositories",
            path=data_dir / "repos",
            category=CATEGORY_INFO,
            note="repository cache",
        ),
    ]

def _locked_roots(config: Config) -> list[RootEntry]:
    """Roots that are shown but never deleted."""
    return [
        RootEntry(
            key="state",
            label="State",
            path=config.state_dir,
            category=CATEGORY_LOCKED,
            note="TUI state",
        ),
        RootEntry(
            key="cache",
            label="Cache",
            path=config.cache_dir,
            category=CATEGORY_LOCKED,
            note="regenerable cache",
        ),
        RootEntry(
            key="config",
            label="Config",
            path=config.config_dir,
            category=CATEGORY_LOCKED,
            note="user configuration",
        ),
    ]
