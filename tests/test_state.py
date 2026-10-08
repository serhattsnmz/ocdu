"""Tests for ocdu.state (pinned session ids)."""

from __future__ import annotations
import json
from ocdu.state import pinned_session_ids

def _write_state(config, payload) -> None:
    path = config.state_dir / "session.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, str):
        path.write_text(payload, encoding="utf-8")
    else:
        path.write_text(json.dumps(payload), encoding="utf-8")

class TestPinnedSessionIds:

    def test_missing_file(self, config_factory):
        assert pinned_session_ids(config_factory()) == set()

    def test_malformed_file(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, "{broken")
        assert pinned_session_ids(cfg) == set()

    def test_pinned_not_a_list(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, {"pinned": "abc"})
        assert pinned_session_ids(cfg) == set()

    def test_top_level_not_a_dict(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, "[1, 2]")
        assert pinned_session_ids(cfg) == set()

    def test_returns_string_ids(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, {"pinned": ["a", 2, "b"]})
        assert pinned_session_ids(cfg) == {"a", "2", "b"}

    def test_missing_pinned_key(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, {"other": ["a"]})
        assert pinned_session_ids(cfg) == set()
