"""Tests for ocdu.export (Markdown transcripts and JSON export)."""

from __future__ import annotations
import json
import pytest
import ocdu.export as export_module
from ocdu.export import (
    TranscriptOptions,
    export_json,
    export_markdown,
    safe_filename,
    to_markdown,
    _format_duration,
    _format_message,
    _format_part,
)
from ocdu.opencode import CliResult
from tests.factories import MessageFactory, PartFactory, SessionFactory

class TestSafeFilename:

    def test_replaces_invalid_characters(self):
        assert safe_filename("My Session: v1/2", "fb") == "My Session_ v1_2"

    def test_keeps_allowed_punctuation(self):
        assert safe_filename("a-b_c.d", "fb") == "a-b_c.d"

    def test_keeps_unicode_letters(self):
        assert safe_filename("café", "fb") == "café"

    def test_empty_falls_back(self):
        assert safe_filename("   ", "fb") == "fb"

    def test_truncates_to_80(self):
        assert len(safe_filename("x" * 200, "fb")) == 80

class TestFormatDuration:

    def test_positive(self):
        assert _format_duration(1000, 1500) == " · 0.5s"

    def test_zero(self):
        assert _format_duration(1000, 1000) == " · 0.0s"

    def test_reversed_negative(self):
        assert _format_duration(2000, 1000) == ""

    def test_non_numeric(self):
        assert _format_duration(None, 1000) == ""
        assert _format_duration(1000, "x") == ""

class TestFormatPart:

    def test_text(self):
        assert _format_part({"type": "text", "text": "hi"}, TranscriptOptions()) == "hi\n\n"

    def test_synthetic_text_skipped(self):
        assert _format_part({"type": "text", "text": "hi", "synthetic": True}, TranscriptOptions()) == ""

    def test_reasoning_included_when_enabled(self):
        out = _format_part({"type": "reasoning", "text": "think"}, TranscriptOptions(thinking=True))
        assert "_Thinking:_" in out and "think" in out

    def test_reasoning_omitted_by_default(self):
        assert _format_part({"type": "reasoning", "text": "think"}, TranscriptOptions()) == ""

    def test_tool_details(self):
        part = {
            "type": "tool",
            "tool": "bash",
            "state": {"input": {"cmd": "ls"}, "status": "completed", "output": "files"},
        }
        out = _format_part(part, TranscriptOptions(tool_details=True))
        assert "**Tool: bash**" in out
        assert "**Input:**" in out
        assert "**Output:**" in out

    def test_tool_error(self):
        part = {"type": "tool", "tool": "bash", "state": {"status": "error", "error": "boom"}}
        assert "**Error:**" in _format_part(part, TranscriptOptions())

    def test_tool_details_disabled(self):
        part = {"type": "tool", "tool": "bash", "state": {"input": {"cmd": "ls"}}}
        out = _format_part(part, TranscriptOptions(tool_details=False))
        assert "**Input:**" not in out
        assert "**Tool: bash**" in out

    def test_unknown_type(self):
        assert _format_part({"type": "snapshot"}, TranscriptOptions()) == ""

class TestFormatMessage:

    def test_user(self):
        message = {"info": {"role": "user"}, "parts": [{"type": "text", "text": "q"}]}
        assert _format_message(message, TranscriptOptions()).startswith("## User\n\n")

    def test_assistant_metadata(self):
        message = {
            "info": {
                "role": "assistant",
                "agent": "build",
                "providerID": "openai",
                "modelID": "gpt",
                "time": {"created": 1000, "completed": 1500},
            },
            "parts": [],
        }
        out = _format_message(message, TranscriptOptions(assistant_metadata=True))
        assert out.startswith("## Assistant (")
        assert "openai/gpt" in out
        assert "0.5s" in out

    def test_assistant_metadata_disabled(self):
        message = {"info": {"role": "assistant", "agent": "build"}, "parts": []}
        assert _format_message(message, TranscriptOptions(assistant_metadata=False)) == "## Assistant\n\n"

    def test_assistant_nested_model_object(self):
        message = {
            "info": {
                "role": "assistant",
                "agent": "build",
                "model": {"modelID": "gpt", "providerID": "openai"},
            },
            "parts": [],
        }
        out = _format_message(message, TranscriptOptions(assistant_metadata=True))
        assert "openai/gpt" in out


class TestToMarkdown:

    def test_basic_structure(self):
        session = {"title": "T", "id": "s1", "time_created": 1_700_000_000_000, "time_updated": 1_700_000_000_000}
        messages = [
            {"info": {"role": "user", "id": "m2", "time": {"created": 200}}, "parts": [{"type": "text", "text": "b"}]},
            {"info": {"role": "user", "id": "m1", "time": {"created": 100}}, "parts": [{"type": "text", "text": "a"}]},
        ]
        out = to_markdown(session, messages, TranscriptOptions())
        assert out.startswith("# T")
        assert "**Session ID:** s1" in out
        assert out.index("## User\n\na") < out.index("## User\n\nb")

    def test_invalid_timestamps_do_not_crash(self):
        session = {"title": "T", "id": "s1", "time_created": -1, "time_updated": 10**18}
        out = to_markdown(session, [], TranscriptOptions())
        assert out.startswith("# T")
        assert "**Created:**" in out

    def test_none_message_time_sorts_first(self):
        session = {"title": "T", "id": "s1", "time_created": 0, "time_updated": 0}
        messages = [
            {"info": {"role": "user", "id": "b", "time": {"created": None}},
             "parts": [{"type": "text", "text": "b"}]},
            {"info": {"role": "user", "id": "a", "time": {"created": 100}},
             "parts": [{"type": "text", "text": "a"}]},
        ]
        out = to_markdown(session, messages, TranscriptOptions())
        assert out.count("## User") == 2
        assert out.index("## User\n\nb") < out.index("## User\n\na")

class TestExportMarkdown:

    def test_missing_session_raises(self, make_db, config_factory, tmp_path):
        db_path = make_db({})
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)
        with pytest.raises(ValueError):
            export_markdown(cfg, "nope", tmp_path / "out.md")

    def test_writes_file(self, make_db, config_factory, tmp_path):
        rows = {
            "session": [SessionFactory(id="s1", title="T")],
            "message": [MessageFactory(id="m1", session_id="s1", data='{"role": "user", "time": {"created": 100}}')],
            "part": [PartFactory(id="p1", message_id="m1", session_id="s1", data='{"type": "text", "text": "hi"}')],
        }
        db_path = make_db(rows)
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)
        dest = tmp_path / "nested" / "out.md"
        result = export_markdown(cfg, "s1", dest)
        assert result == dest
        assert "# T" in dest.read_text(encoding="utf-8")

class TestExportJson:

    def _config(self, config_factory, tmp_path):
        return config_factory(OPENCODE_DATA_DIR=str(tmp_path / "data"), OPENCODE_DB_FILE="opencode.db")

    def test_success(self, config_factory, tmp_path, monkeypatch):
        fake = CliResult([], 0, '{"ok": true}', "")
        monkeypatch.setattr(export_module, "export_session_json", lambda *_a, **_k: fake)
        dest = tmp_path / "out.json"
        export_json(self._config(config_factory, tmp_path), "s1", dest)
        assert json.loads(dest.read_text(encoding="utf-8")) == {"ok": True}

    def test_failure_raises(self, config_factory, tmp_path, monkeypatch):
        fake = CliResult([], 1, "", "boom")
        monkeypatch.setattr(export_module, "export_session_json", lambda *_a, **_k: fake)
        with pytest.raises(RuntimeError):
            export_json(self._config(config_factory, tmp_path), "s1", tmp_path / "out.json")

    def test_empty_output_raises(self, config_factory, tmp_path, monkeypatch):
        fake = CliResult([], 0, "   ", "")
        monkeypatch.setattr(export_module, "export_session_json", lambda *_a, **_k: fake)
        with pytest.raises(RuntimeError):
            export_json(self._config(config_factory, tmp_path), "s1", tmp_path / "out.json")
