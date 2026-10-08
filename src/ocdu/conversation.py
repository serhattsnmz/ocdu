"""Load a session's conversation as user messages with their pure LLM replies.

Only ``text`` parts are considered. Assistant ``reasoning`` / ``tool`` / ``patch``
/ ``file`` / ``compaction`` / ``step-*`` parts are ignored, so a reply is the flat
model output with no tool or thinking noise.
"""

from __future__ import annotations
import json
import sqlite3
from .model import MessageTurn

def _load_parts(
    connection: sqlite3.Connection, session_id: str
) -> dict[str, list[dict]]:
    """Group every part of a session by its message id, in chronological order."""
    parts_by_message: dict[str, list[dict]] = {}
    for row in connection.execute(
        "SELECT id, message_id, session_id, data FROM part WHERE session_id = ? "
        "ORDER BY time_created, id",
        (session_id,),
    ):
        try:
            part = json.loads(row["data"])
        except (TypeError, json.JSONDecodeError):
            part = {}
        if not isinstance(part, dict):
            part = {}
        part.setdefault("id", row["id"])
        part.setdefault("messageID", row["message_id"])
        part.setdefault("sessionID", row["session_id"])
        parts_by_message.setdefault(row["message_id"], []).append(part)
    return parts_by_message

def load_session_messages(
    connection: sqlite3.Connection, session_id: str
) -> list[dict]:
    """Return ``[{"info": ..., "parts": [...]}]`` ordered by (time_created, id)."""
    message_rows = connection.execute(
        "SELECT id, session_id, data FROM message WHERE session_id = ? "
        "ORDER BY time_created, id",
        (session_id,),
    ).fetchall()
    parts_by_message = _load_parts(connection, session_id)

    messages: list[dict] = []
    for row in message_rows:
        try:
            info = json.loads(row["data"])
        except (TypeError, json.JSONDecodeError):
            info = {}
        if not isinstance(info, dict):
            info = {}
        info.setdefault("id", row["id"])
        info.setdefault("sessionID", row["session_id"])
        messages.append({"info": info, "parts": parts_by_message.get(row["id"], [])})
    return messages

def _text_of(parts: list[dict]) -> str:
    """Join the plain ``text`` parts (skipping synthetic ones)."""
    chunks: list[str] = []
    for part in parts:
        if part.get("type") != "text" or part.get("synthetic"):
            continue
        text = str(part.get("text") or "").strip()
        if text:
            chunks.append(text)
    return "\n\n".join(chunks)

def conversation_turns(
    connection: sqlite3.Connection, session_id: str
) -> list[MessageTurn]:
    """Pair each user message with the assistant reply that follows it."""
    messages = load_session_messages(connection, session_id)
    turns: list[MessageTurn] = []
    current: dict | None = None
    reply_chunks: list[str] = []

    def flush() -> None:
        """Append the pending user turn and its reply, if any."""
        if current is None:
            return
        turns.append(
            MessageTurn(
                user_id=str(current["info"].get("id", "")),
                user_time=int((current["info"].get("time") or {}).get("created") or 0),
                user_text=_text_of(current["parts"]),
                reply_text="\n\n".join(reply_chunks),
            )
        )

    for message in messages:
        role = message["info"].get("role")
        if role == "user":
            flush()
            current = message
            reply_chunks = []
        elif role == "assistant" and current is not None:
            text = _text_of(message["parts"])
            if text:
                reply_chunks.append(text)
    flush()
    return turns
