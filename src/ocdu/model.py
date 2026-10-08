"""Data model types shared across ocdu."""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path

# Root categories -----------------------------------------------------------
CATEGORY_MANAGED = "managed"  # ocdu may clean / operate on this root
CATEGORY_INFO = "info"  # shown for information; OpenCode manages it itself
CATEGORY_LOCKED = "locked"  # shown but never deleted (credentials / config)
CATEGORY_BACKUP = "backup"  # ocdu-created backup archives

# Display order for the footprint breakdown.
CATEGORY_ORDER = (
    CATEGORY_MANAGED,
    CATEGORY_INFO,
    CATEGORY_LOCKED,
    CATEGORY_BACKUP,
)

@dataclass
class RootEntry:
    """A single data location (file or directory) tracked by ocdu."""

    key: str
    label: str
    path: Path
    category: str
    note: str = ""
    companions: list[Path] = field(default_factory=list)
    exists: bool = False
    size_bytes: int = 0
    file_count: int = 0

    @property
    def all_paths(self) -> list[Path]:
        """Primary path plus any companion paths (e.g. ``-wal``/``-shm``)."""
        return [self.path, *self.companions]

@dataclass
class ScanReport:
    """Result of scanning every tracked root."""

    entries: list[RootEntry] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        """Return the summed byte size of all entries."""
        return sum(entry.size_bytes for entry in self.entries)

    def get(self, key: str) -> RootEntry | None:
        """Return the entry with ``key`` or ``None`` when absent."""
        for entry in self.entries:
            if entry.key == key:
                return entry
        return None

@dataclass
class SessionSize:
    """Aggregated size of everything a session delete would remove."""

    session_id: str
    title: str
    directory: str
    is_root: bool
    message_count: int
    child_count: int
    event_bytes: int
    message_bytes: int
    part_bytes: int
    session_message_bytes: int
    todo_bytes: int
    time_updated: int
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0

    @property
    def total_bytes(self) -> int:
        """Return the summed size of all session artifacts."""
        return (
            self.event_bytes
            + self.message_bytes
            + self.part_bytes
            + self.session_message_bytes
            + self.todo_bytes
        )

@dataclass
class MessageTurn:
    """One user message and the pure assistant reply that follows it."""

    user_id: str
    user_time: int
    user_text: str
    reply_text: str

@dataclass
class DirectorySummary:
    """A working directory that holds one or more sessions."""

    directory: str
    size_bytes: int
    session_count: int
    root_count: int
    last_updated: int
    exists: bool

@dataclass
class OrphanReport:
    """Provably-orphaned data that ocdu may clean."""

    orphan_event_sequences: int = 0
    orphan_event_bytes: int = 0
    orphan_session_diff_files: list[Path] = field(default_factory=list)
    orphan_session_diff_bytes: int = 0

    @property
    def event_bytes(self) -> int:
        """Return the size of orphaned event data in bytes."""
        return self.orphan_event_bytes

    @property
    def session_diff_bytes(self) -> int:
        """Return the size of orphaned session diff files in bytes."""
        return self.orphan_session_diff_bytes

    @property
    def total_bytes(self) -> int:
        """Return the combined size of all orphaned data in bytes."""
        return self.orphan_event_bytes + self.orphan_session_diff_bytes

@dataclass
class BackupResult:
    """Outcome of creating a backup archive."""

    path: Path
    db_bytes: int
    total_bytes: int
    extra_files: int
    removed_old: list[Path] = field(default_factory=list)

@dataclass
class PruneResult:
    """Outcome of a safe orphan prune."""

    orphan_event_sequences: int = 0
    orphan_event_bytes: int = 0
    session_diff_files: int = 0
    session_diff_bytes: int = 0

    @property
    def freed_bytes(self) -> int:
        """Return the total number of bytes reclaimed."""
        return self.orphan_event_bytes + self.session_diff_bytes

@dataclass
class VacuumResult:
    """Outcome of a VACUUM / checkpoint."""

    before_bytes: int
    after_bytes: int

    @property
    def saved_bytes(self) -> int:
        """Return the number of bytes saved by the vacuum."""
        return max(0, self.before_bytes - self.after_bytes)
