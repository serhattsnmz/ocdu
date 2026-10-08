"""Tests for ocdu.conversation (pairing user turns with assistant replies)."""

from __future__ import annotations
import json
from ocdu.conversation import conversation_turns, load_session_messages
from ocdu.db import Database
from tests.factories import MessageFactory, PartFactory

def _msg(mid: str, role: str, created: int = 1000, session: str = "s") -> dict:
    return MessageFactory(
        id=mid, session_id=session, time_created=created,
        data=json.dumps({"role": role, "time": {"created": created}}),
    )

def _part(pid: str, mid: str, data: dict, session: str = "s") -> dict:
    return PartFactory(id=pid, message_id=mid, session_id=session, data=json.dumps(data))

def _turns(make_db, rows: dict) -> list:
    db = Database(make_db(rows))
    with db.open() as connection:
        return conversation_turns(connection, "s")

class TestLoadSessionMessages:

    def test_orders_by_time_then_id(self, make_db):
        rows = {"message": [_msg("m2", "assistant", 200), _msg("m1", "user", 100)], "part": []}
        db = Database(make_db(rows))
        with db.open() as connection:
            messages = load_session_messages(connection, "s")
        assert [message["info"]["id"] for message in messages] == ["m1", "m2"]

    def test_invalid_json_message_data(self, make_db):
        rows = {"message": [MessageFactory(id="m1", session_id="s", data="{bad")]}
        db = Database(make_db(rows))
        with db.open() as connection:
            messages = load_session_messages(connection, "s")
        assert messages[0]["info"]["id"] == "m1"
        assert messages[0]["info"]["sessionID"] == "s"

    def test_other_sessions_excluded(self, make_db):
        rows = {"message": [_msg("m1", "user", session="other")], "part": []}
        db = Database(make_db(rows))
        with db.open() as connection:
            assert load_session_messages(connection, "s") == []

class TestConversationTurns:

    def test_pairs_user_and_assistant(self, make_db):
        rows = {
            "message": [_msg("m1", "user", 1000), _msg("m2", "assistant", 1100), _msg("m3", "user", 1200)],
            "part": [
                _part("p1", "m1", {"type": "text", "text": "hello"}),
                _part("p2", "m2", {"type": "text", "text": "hi there"}),
                _part("p3", "m3", {"type": "text", "text": "second"}),
            ],
        }
        turns = _turns(make_db, rows)
        assert len(turns) == 2
        assert turns[0].user_text == "hello"
        assert turns[0].reply_text == "hi there"
        assert turns[1].user_text == "second"
        assert turns[1].reply_text == ""

    def test_assistant_before_first_user_ignored(self, make_db):
        rows = {
            "message": [_msg("m1", "assistant", 100)],
            "part": [_part("p1", "m1", {"type": "text", "text": "orphan"})],
        }
        assert _turns(make_db, rows) == []

    def test_consecutive_assistant_messages_concatenate(self, make_db):
        rows = {
            "message": [_msg("m1", "user", 100), _msg("m2", "assistant", 110), _msg("m3", "assistant", 120)],
            "part": [
                _part("p1", "m2", {"type": "text", "text": "a"}),
                _part("p2", "m3", {"type": "text", "text": "b"}),
            ],
        }
        assert _turns(make_db, rows)[0].reply_text == "a\n\nb"

    def test_consecutive_user_messages(self, make_db):
        rows = {
            "message": [_msg("m1", "user", 100), _msg("m2", "user", 110)],
            "part": [
                _part("p1", "m1", {"type": "text", "text": "first"}),
                _part("p2", "m2", {"type": "text", "text": "second"}),
            ],
        }
        turns = _turns(make_db, rows)
        assert [turn.user_text for turn in turns] == ["first", "second"]
        assert turns[0].reply_text == ""

    def test_synthetic_and_non_text_parts_skipped(self, make_db):
        rows = {
            "message": [_msg("m1", "user", 100), _msg("m2", "assistant", 110)],
            "part": [
                _part("p1", "m1", {"type": "text", "text": "real"}),
                _part("p2", "m1", {"type": "text", "text": "synthetic", "synthetic": True}),
                _part("p3", "m2", {"type": "reasoning", "text": "thinking"}),
                _part("p4", "m2", {"type": "tool", "tool": "bash"}),
                _part("p5", "m2", {"type": "text", "text": "answer"}),
            ],
        }
        turns = _turns(make_db, rows)
        assert turns[0].user_text == "real"
        assert turns[0].reply_text == "answer"

    def test_multiple_text_parts_joined(self, make_db):
        rows = {
            "message": [_msg("m1", "user", 100)],
            "part": [
                _part("p1", "m1", {"type": "text", "text": "x"}),
                _part("p2", "m1", {"type": "text", "text": "y"}),
            ],
        }
        assert _turns(make_db, rows)[0].user_text == "x\n\ny"

    def test_user_time_defaults_to_zero(self, make_db):
        rows = {"message": [MessageFactory(id="m1", session_id="s", data='{"role": "user"}')], "part": []}
        assert _turns(make_db, rows)[0].user_time == 0

    def test_invalid_part_data_ignored(self, make_db):
        rows = {
            "message": [_msg("m1", "user", 100), _msg("m2", "assistant", 110)],
            "part": [
                _part("p1", "m1", {"type": "text", "text": "q"}),
                PartFactory(id="p2", message_id="m2", session_id="s", data="{bad"),
            ],
        }
        assert _turns(make_db, rows)[0].reply_text == ""

    def test_non_dict_message_data_treated_as_empty(self, make_db):
        rows = {"message": [MessageFactory(id="m1", session_id="s", data="[]")], "part": []}
        db = Database(make_db(rows))
        with db.open() as connection:
            messages = load_session_messages(connection, "s")
        assert messages[0]["info"]["id"] == "m1"

    def test_non_dict_part_data_ignored(self, make_db):
        rows = {
            "message": [_msg("m1", "user", 100), _msg("m2", "assistant", 110)],
            "part": [
                _part("p1", "m1", {"type": "text", "text": "q"}),
                PartFactory(id="p2", message_id="m2", session_id="s", data="[]"),
            ],
        }
        assert _turns(make_db, rows)[0].reply_text == ""
