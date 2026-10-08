"""Read OpenCode's local TUI state (pinned/favourite sessions)."""

from __future__ import annotations
import json
from .config import Config, config as default_config

def pinned_session_ids(config: Config = default_config) -> set[str]:
    """Return the set of pinned (favourite) session ids from the TUI state file."""
    path = config.state_dir / "session.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    pinned = data.get("pinned") if isinstance(data, dict) else None
    if not isinstance(pinned, list):
        return set()
    return {str(item) for item in pinned}
