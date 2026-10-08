"""Wrapper around the official OpenCode CLI.

Destructive operations are delegated to the real ``opencode`` binary so that
OpenCode's own cascade rules (child sessions, events, projections) are applied
exactly as intended.
"""

from __future__ import annotations
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from .config import Config

@dataclass
class CliResult:
    """Outcome of an OpenCode CLI invocation."""

    args: list[str]
    returncode: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        """Return whether the CLI invocation succeeded."""
        return self.returncode == 0

def resolve_bin(config: Config) -> str:
    """Resolve the OpenCode executable path (falls back to the configured name)."""
    return shutil.which(config.opencode_bin) or config.opencode_bin

def run_cli(
    config: Config,
    args: list[str],
    *,
    cwd: Path | None = None,
    timeout: int | None = None,
) -> CliResult:
    """Run an OpenCode CLI command and capture its output."""
    executable = resolve_bin(config)
    full_args = [executable, *args]
    try:
        completed = subprocess.run(
            full_args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout or config.opencode_cli_timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as error:
        return CliResult(full_args, 127, "", str(error))
    except subprocess.TimeoutExpired as error:
        return CliResult(full_args, 124, error.stdout or "", "timed out")
    return CliResult(full_args, completed.returncode, completed.stdout, completed.stderr)

def _working_dir(config: Config, directory: str | None) -> Path:
    """Return the working directory for a CLI call."""
    if directory:
        candidate = Path(directory)
        if candidate.is_dir():
            return candidate
    return config.data_dir

def delete_session(config: Config, session_id: str, directory: str | None = None) -> CliResult:
    """Delete a session using ``opencode session delete``."""
    return run_cli(
        config,
        ["session", "delete", session_id],
        cwd=_working_dir(config, directory),
    )

def export_session_json(config: Config, session_id: str, directory: str | None = None) -> CliResult:
    """Export a session as JSON via ``opencode export`` (JSON on stdout)."""
    return run_cli(
        config,
        ["export", session_id],
        cwd=_working_dir(config, directory),
        timeout=max(config.opencode_cli_timeout, 300),
    )
