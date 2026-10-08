"""Move a session (and its subagent children) to another working directory.

OpenCode resolves a project id from the working directory. To move a session we
replicate that resolution so the session shows up under the target directory:

    git remote  ->  sha1("git-remote:<host>/<path>")
    .git/opencode  (cached id)
    root commit hash
    "global"  (non-git directory)
"""

from __future__ import annotations
import hashlib
import os
import re
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse
from .config import Config

_SCP_RE = re.compile(r"^([^@/:]+@)?([^/:]+):(.+)$")

@dataclass
class TargetProject:
    """Resolved project identity for a target directory."""

    directory: Path
    project_id: str
    worktree: str
    is_git: bool

@dataclass
class MoveResult:
    """Outcome of moving a session."""

    session_id: str
    from_directory: str
    to_directory: str
    project_id: str
    path: str
    moved_sessions: int

def _run_git(directory: Path, args: list[str]) -> str | None:
    """Run a git command and return its stripped stdout, or ``None`` on failure."""
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(directory),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if completed.returncode != 0:
        return None
    return completed.stdout.strip()

def _sha1(value: str) -> str:
    """Hash a string with SHA-1 to mirror OpenCode's project id."""
    # SHA-1 mirrors OpenCode's project-id algorithm; it is not used for security.
    return hashlib.sha1(value.encode("utf-8")).hexdigest()  # noqa: S324

def _normalize_remote(url: str | None) -> str | None:
    """Normalize a git remote URL to ``host/path`` (mirrors OpenCode)."""
    if not url:
        return None
    value = url.strip()
    if not value:
        return None

    def parts(host: str, name: str) -> str | None:
        """Build a normalized ``host/path`` remote identifier."""
        pathname = name.lstrip("/")
        pathname = re.sub(r"\.git/?$", "", pathname)
        pathname = pathname.rstrip("/")
        if not host or not pathname:
            return None
        return f"{host.lower()}/{pathname}"

    try:
        parsed = urlparse(value)
    except ValueError:
        parsed = None

    # Mirror OpenCode: a successfully parsed URL never falls through to the
    # scp-like branch below, even when it has no hostname (e.g. Windows paths
    # such as ``C:\repos\project``). In that case we return None so the caller
    # falls back to the cached id / root commit / global.
    if parsed is not None and parsed.scheme:
        if parsed.scheme == "file":
            return None
        if parsed.hostname and parsed.path:
            return parts(parsed.hostname, parsed.path)
        return None

    match = _SCP_RE.match(value)
    if match:
        return parts(match.group(2), match.group(3))
    return None

def _cached_id(git_dir: Path | None) -> str | None:
    """Read the cached project id from ``.git/opencode`` if present."""
    if git_dir is None:
        return None
    try:
        value = (git_dir / "opencode").read_text(encoding="utf-8").strip()
        return value or None
    except OSError:
        return None

def resolve_target(directory: Path) -> TargetProject:
    """Resolve the OpenCode project id for a target directory."""
    directory = directory.expanduser()
    resolved = directory.resolve()

    if not resolved.is_dir():
        anchor = Path(resolved.anchor) if resolved.anchor else resolved
        return TargetProject(directory=resolved, project_id="global", worktree=str(anchor), is_git=False)

    toplevel = _run_git(resolved, ["rev-parse", "--show-toplevel"])
    if toplevel is None:
        anchor = Path(resolved.anchor) if resolved.anchor else resolved
        return TargetProject(directory=resolved, project_id="global", worktree=str(anchor), is_git=False)

    worktree = Path(toplevel).resolve()
    git_dir_raw = _run_git(resolved, ["rev-parse", "--absolute-git-dir"])
    git_dir = Path(git_dir_raw).resolve() if git_dir_raw else None

    remote = _normalize_remote(_run_git(resolved, ["remote", "get-url", "origin"]))
    project_id = _sha1(f"git-remote:{remote}") if remote else None
    if project_id is None:
        project_id = _cached_id(git_dir)
    if project_id is None:
        root = _run_git(resolved, ["rev-list", "--max-parents=0", "HEAD"])
        project_id = root.splitlines()[0].strip() if root else None
    if project_id is None:
        project_id = "global"

    return TargetProject(
        directory=resolved,
        project_id=project_id,
        worktree=str(worktree),
        is_git=True,
    )

def compute_path(worktree: str, directory: str) -> str:
    """Compute the relative session path (forward slashes, "" at the root)."""
    try:
        rel = os.path.relpath(directory, worktree)
    except ValueError:
        rel = directory
    rel = rel.replace("\\", "/")
    return "" if rel == "." else rel

def _ensure_project_row(connection: sqlite3.Connection, project: TargetProject) -> None:
    """Insert the target project when missing so the session FK stays valid."""
    now = int(time.time() * 1000)
    connection.execute(
        "INSERT OR IGNORE INTO project "
        "(id, worktree, vcs, name, time_created, time_updated, sandboxes) "
        "VALUES (?, ?, ?, ?, ?, ?, '[]')",
        (
            project.project_id,
            project.worktree,
            "git" if project.is_git else None,
            Path(project.worktree).name,
            now,
            now,
        ),
    )

def descendants(connection: sqlite3.Connection, session_id: str) -> list[str]:
    """Return all descendant session ids (fetched with a single query)."""
    children: dict[str, list[str]] = {}
    for row in connection.execute(
        "SELECT id, parent_id FROM session WHERE parent_id IS NOT NULL"
    ):
        children.setdefault(row["parent_id"], []).append(row["id"])
    result: list[str] = []
    queue = [session_id]
    while queue:
        for child in children.get(queue.pop(), []):
            result.append(child)
            queue.append(child)
    return result

def move_session(
    config: Config,
    session_id: str,
    target: Path,
    *,
    force: bool = False,
) -> MoveResult:
    """Move a session and its children to ``target``. Returns a ``MoveResult``."""
    target = target.expanduser()
    if not target.is_dir() and not force:
        raise FileNotFoundError(f"target directory does not exist: {target}")

    connection = sqlite3.connect(str(config.db_path), timeout=30.0)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        row = connection.execute(
            "SELECT id, directory, parent_id FROM session WHERE id = ?", (session_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"session not found: {session_id}")

        project = resolve_target(target)
        new_directory = project.directory.as_posix()
        new_path = compute_path(project.worktree, str(project.directory))

        _ensure_project_row(connection, project)
        ids = [session_id, *descendants(connection, session_id)]
        connection.executemany(
            "UPDATE session SET directory = ?, path = ?, project_id = ? WHERE id = ?",
            [(new_directory, new_path, project.project_id, sid) for sid in ids],
        )
        connection.commit()

        return MoveResult(
            session_id=session_id,
            from_directory=row["directory"],
            to_directory=new_directory,
            project_id=project.project_id,
            path=new_path,
            moved_sessions=len(ids),
        )
    finally:
        connection.close()
