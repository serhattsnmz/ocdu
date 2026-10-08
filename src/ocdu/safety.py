"""Safety helpers: detect a live OpenCode instance and guard locked paths."""

from __future__ import annotations
import sqlite3
import subprocess
import sys
from dataclasses import dataclass
from .config import Config

@dataclass
class SafetyStatus:
    """Result of probing the environment before a write operation."""

    db_in_use: bool
    opencode_processes: list[str]

    @property
    def safe_for_exclusive(self) -> bool:
        """Whether an exclusive operation (VACUUM) is likely to succeed."""
        return not self.db_in_use and not self.opencode_processes

    def describe(self) -> str:
        """Describe why an exclusive operation may be blocked."""
        blocks: list[str] = []
        if self.db_in_use:
            blocks.append("database is currently locked by a writer")
        if self.opencode_processes:
            lines = ["OpenCode process(es) running:"]
            lines.extend(f"  - {process}" for process in self.opencode_processes)
            blocks.append("\n".join(lines))
        return "\n".join(blocks) if blocks else "no OpenCode instance detected"

def database_in_use(config: Config) -> bool:
    """Return True if the database is held by an active writer."""
    if not config.db_path.is_file():
        return False
    uri = config.db_path.resolve().as_uri() + "?mode=rw"
    try:
        connection = sqlite3.connect(uri, uri=True, timeout=1.0)
    except sqlite3.Error:
        return True
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("ROLLBACK")
        return False
    except sqlite3.OperationalError:
        return True
    finally:
        connection.close()

def opencode_processes() -> list[str]:
    """List running OpenCode processes (best effort, platform dependent)."""
    try:
        if sys.platform == "win32":
            result = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq opencode.exe", "/NH"],
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return [line.strip() for line in result.stdout.splitlines() if "opencode" in line.lower()]
        result = subprocess.run(
            ["pgrep", "-a", "opencode"], capture_output=True, text=True, timeout=5
        )
        return [line.strip() for line in result.stdout.splitlines() if line.strip()]
    except (OSError, subprocess.SubprocessError):
        return []

def probe(config: Config) -> SafetyStatus:
    """Probe the environment for a live OpenCode instance."""
    return SafetyStatus(
        db_in_use=database_in_use(config),
        opencode_processes=opencode_processes(),
    )
