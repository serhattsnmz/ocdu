"""Export sessions as JSON (OpenCode-compatible) or Markdown transcripts."""

from __future__ import annotations
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from .config import Config
from .conversation import load_session_messages
from .db import Database
from .opencode import export_session_json
from .util import format_datetime

@dataclass
class TranscriptOptions:
    """What to include in a Markdown transcript."""

    thinking: bool = False
    tool_details: bool = True
    assistant_metadata: bool = True

def _format_duration(created: object, completed: object) -> str:
    """Format the elapsed time between two millisecond timestamps."""
    if isinstance(created, (int, float)) and isinstance(completed, (int, float)) and completed >= created:
        return f" · {(completed - created) / 1000:.1f}s"
    return ""

def _format_part(part: dict, options: TranscriptOptions) -> str:
    """Render a single message part as Markdown."""
    kind = part.get("type")
    if kind == "text":
        if part.get("synthetic"):
            return ""
        return f"{part.get('text', '')}\n\n"
    if kind == "reasoning":
        if options.thinking:
            return f"_Thinking:_\n\n{part.get('text', '')}\n\n"
        return ""
    if kind == "tool":
        state = part.get("state") or {}
        result = f"**Tool: {part.get('tool', '')}**\n"
        if options.tool_details and state.get("input"):
            result += f"\n**Input:**\n```json\n{json.dumps(state['input'], indent=2)}\n```\n"
        if options.tool_details and state.get("status") == "completed" and state.get("output"):
            result += f"\n**Output:**\n```\n{state['output']}\n```\n"
        if options.tool_details and state.get("status") == "error" and state.get("error"):
            result += f"\n**Error:**\n```\n{state['error']}\n```\n"
        return result + "\n"
    return ""

def _format_message(message: dict, options: TranscriptOptions) -> str:
    """Render one message (header and parts) as Markdown."""
    info = message["info"]
    result = ""
    if info.get("role") == "user":
        result += "## User\n\n"
    elif options.assistant_metadata:
        agent = str(info.get("agent", "")).title()
        model = info.get("modelID") or (info.get("model") or {}).get("modelID", "")
        provider = info.get("providerID") or (info.get("model") or {}).get("providerID", "")
        model_label = f"{provider}/{model}" if provider else model
        duration = _format_duration(
            (info.get("time") or {}).get("created"), (info.get("time") or {}).get("completed")
        )
        detail = " · ".join(part for part in (agent, model_label) if part)
        result += f"## Assistant ({detail}{duration})\n\n" if detail else "## Assistant\n\n"
    else:
        result += "## Assistant\n\n"

    for part in message["parts"]:
        result += _format_part(part, options)
    return result

def _safe_datetime(epoch_ms: object) -> datetime:
    """Convert a millisecond epoch to a datetime, falling back to the epoch."""
    try:
        return datetime.fromtimestamp(float(epoch_ms or 0) / 1000)
    except (OverflowError, OSError, ValueError, TypeError):
        return datetime.fromtimestamp(0)

def _message_sort_key(message: dict) -> tuple[float, str]:
    """Return a comparison-safe sort key for a message dict."""
    created = (message["info"].get("time") or {}).get("created")
    timestamp = created if isinstance(created, (int, float)) else 0
    return timestamp, str(message["info"].get("id", ""))

def to_markdown(session: dict, messages: list[dict], options: TranscriptOptions) -> str:
    """Render a session as a Markdown transcript."""
    created = _safe_datetime(session.get("time_created"))
    updated = _safe_datetime(session.get("time_updated"))
    lines = [
        f"# {session.get('title', '')}",
        "",
        f"**Session ID:** {session.get('id', '')}",
        f"**Created:** {format_datetime(created)}",
        f"**Updated:** {format_datetime(updated)}",
        "",
        "---",
        "",
    ]
    ordered = sorted(messages, key=_message_sort_key)
    for message in ordered:
        lines.append(_format_message(message, options))
        lines.append("---\n")
    return "\n".join(lines)

def _load_session(connection: sqlite3.Connection, session_id: str) -> dict | None:
    """Load one session row as a dict, or ``None`` when missing."""
    row = connection.execute(
        "SELECT id, title, directory, time_created, time_updated FROM session WHERE id = ?",
        (session_id,),
    ).fetchone()
    return dict(row) if row else None

def safe_filename(name: str, fallback: str) -> str:
    """Turn a session title into a safe file name stem."""
    cleaned = "".join(c if c.isalnum() or c in " -_." else "_" for c in name).strip()
    cleaned = cleaned[:80].strip() or fallback
    return cleaned

def export_markdown(
    config: Config,
    session_id: str,
    dest: Path,
    options: TranscriptOptions | None = None,
) -> Path:
    """Write a Markdown transcript for one session and return the file path."""
    options = options or TranscriptOptions()
    db = Database(config.db_path)
    with db.open() as connection:
        session = _load_session(connection, session_id)
        if session is None:
            raise ValueError(f"session not found: {session_id}")
        messages = load_session_messages(connection, session_id)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(to_markdown(session, messages, options), encoding="utf-8")
    return dest

def export_json(
    config: Config,
    session_id: str,
    dest: Path,
    directory: str | None = None,
) -> Path:
    """Write an OpenCode-compatible JSON export for one session (via the CLI)."""
    result = export_session_json(config, session_id, directory)
    if not result.ok or not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "opencode export failed")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(result.stdout, encoding="utf-8")
    return dest
