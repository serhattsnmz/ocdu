"""Read and write OpenCode's local TUI state (pinned/favourite sessions)."""

from __future__ import annotations
import contextlib
import json
import os
from pathlib import Path
from .config import Config, config as default_config

def _state_path(config: Config) -> Path:
    """Return the path of OpenCode's session TUI state file."""
    return config.state_dir / "session.json"

def _load_state(config: Config) -> dict:
    """Load the raw session state mapping, or an empty mapping when unreadable."""
    try:
        data = json.loads(_state_path(config).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}

def _pinned_list(data: dict) -> list[str]:
    """Return the normalised ``pinned`` list from a raw state mapping."""
    pinned = data.get("pinned")
    if not isinstance(pinned, list):
        return []
    return [str(item) for item in pinned]

def pinned_session_ids(config: Config = default_config) -> set[str]:
    """Return the set of pinned (favourite) session ids from the TUI state file."""
    return set(_pinned_list(_load_state(config)))

def toggle_pinned(config: Config, session_id: str) -> bool:
    """Add or remove ``session_id`` from the pinned list and return the new state.

    Other keys already present in the state file are preserved. New pins are
    appended at the end (matching OpenCode's ``togglePin`` order) and the write is
    atomic (temp file + ``os.replace``) so a crash cannot truncate the file.
    """
    data = _load_state(config)
    pinned = _pinned_list(data)
    if session_id in pinned:
        pinned = [item for item in pinned if item != session_id]
    else:
        pinned.append(session_id)
    data["pinned"] = pinned
    path = _state_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    temp_file = path.with_name(path.name + ".part")
    try:
        temp_file.write_text(payload, encoding="utf-8")
        os.replace(temp_file, path)
    except BaseException:
        with contextlib.suppress(OSError):
            temp_file.unlink()
        raise
    return session_id in pinned
