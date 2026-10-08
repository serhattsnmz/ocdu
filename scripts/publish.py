"""Publish ocdu to its private and public remotes.

The private target pushes ``master`` to ``origin`` unchanged. The public target builds a
filtered ``publish`` branch by cloning the repository, dropping every path listed in
``publish.ignore`` from the entire history with ``git-filter-repo``, and force-pushing the
result to ``github``. The working tree and local commits are never modified.
"""

from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IGNORE_FILE = "publish.ignore"
PRIVATE_REMOTE = "origin"
PUBLIC_REMOTE = "github"
SOURCE_BRANCH = "master"
PUBLIC_BRANCH = "publish"

class PublishError(RuntimeError):
    """Raised when a publish step cannot proceed."""

def repo_root() -> Path:
    """Return the absolute path of the current git repository root."""
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        check=True,
        capture_output=True,
        text=True,
    )
    return Path(result.stdout.strip())

def run(args: list[str], cwd: Path | None = None, dry_run: bool = False) -> None:
    """Run a command, printing it first and honoring ``dry_run``."""
    location = f"(cd {cwd}) " if cwd is not None else ""
    print(f"+ {location}{' '.join(args)}")
    if dry_run:
        return
    subprocess.run(args, cwd=cwd, check=True)

def parse_ignore(path: Path) -> list[str]:
    """Read the ignore file and return normalized, validated path entries."""
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise PublishError(f"{path.name} not found at the repository root") from exc
    entries: list[str] = []
    for line in raw.splitlines():
        item = line.strip()
        if not item or item.startswith("#"):
            continue
        item = item.rstrip("/")
        if not item:
            continue
        if item.startswith(("/", "\\")) or ".." in Path(item).parts:
            raise PublishError(f"invalid path in {path.name}: {line.strip()!r}")
        entries.append(item)
    if not entries:
        raise PublishError(f"{path.name} does not list any path to exclude")
    return entries

def remove_tree(path: Path) -> None:
    """Remove a directory tree, clearing read-only attributes so Windows can delete it."""
    for current, subdirs, files in os.walk(path, topdown=False):
        for name in files:
            target = Path(current, name)
            target.chmod(0o700)
            target.unlink()
        for name in subdirs:
            target = Path(current, name)
            target.chmod(0o700)
            target.rmdir()
    path.chmod(0o700)
    path.rmdir()

def ensure_remote(name: str, cwd: Path) -> str:
    """Return the URL of a configured remote or raise ``PublishError``."""
    result = subprocess.run(
        ["git", "remote", "get-url", name],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise PublishError(f"remote {name!r} is not configured")
    return result.stdout.strip()

def filter_repo_command(paths: list[str]) -> list[str]:
    """Build the ``git-filter-repo`` command that removes ``paths`` from history."""
    executable = shutil.which("git-filter-repo")
    command = [executable] if executable else [sys.executable, "-m", "git_filter_repo"]
    command.extend(["--force", "--invert-paths"])
    for item in paths:
        command.extend(["--path", item])
    return command

def publish_private(root: Path, dry_run: bool) -> None:
    """Push the source branch to the private remote without filtering."""
    if not dry_run:
        ensure_remote(PRIVATE_REMOTE, root)
    run(["git", "push", PRIVATE_REMOTE, SOURCE_BRANCH], cwd=root, dry_run=dry_run)

def publish_public(root: Path, dry_run: bool) -> None:
    """Build the filtered public branch from committed state and push it to the public remote."""
    paths = parse_ignore(root / IGNORE_FILE)
    url = ensure_remote(PUBLIC_REMOTE, root) if not dry_run else f"<{PUBLIC_REMOTE}-url>"
    temp_dir = Path("<tmp>") if dry_run else Path(tempfile.mkdtemp(prefix="ocdu-publish-"))
    push_ref = f"{SOURCE_BRANCH}:refs/heads/{PUBLIC_BRANCH}"
    steps = [
        (["git", "clone", "--no-local", "--branch", SOURCE_BRANCH, str(root), str(temp_dir)], None),
        (filter_repo_command(paths), temp_dir),
        (["git", "remote", "add", PUBLIC_REMOTE, url], temp_dir),
        (["git", "fetch", PUBLIC_REMOTE], temp_dir),
        (["git", "push", "--force-with-lease", PUBLIC_REMOTE, push_ref], temp_dir),
    ]
    try:
        for args, cwd in steps:
            run(args, cwd=cwd, dry_run=dry_run)
    finally:
        if not dry_run:
            try:
                remove_tree(temp_dir)
            except OSError as error:
                print(f"warning: could not remove {temp_dir}: {error}", file=sys.stderr)

def main() -> int:
    """Parse arguments and dispatch to the requested publish target."""
    parser = argparse.ArgumentParser(description="Publish ocdu to its remotes.")
    parser.add_argument("--target", choices=("private", "public"), required=True, help="remote to publish to")
    parser.add_argument("--dry-run", action="store_true", help="print the commands without running them")
    args = parser.parse_args()
    root = repo_root()
    if args.target == "private":
        publish_private(root, args.dry_run)
    else:
        publish_public(root, args.dry_run)
    return 0

if __name__ == "__main__":
    try:
        sys.exit(main())
    except (PublishError, subprocess.CalledProcessError) as error:
        print(f"error: {error}", file=sys.stderr)
        sys.exit(1)
