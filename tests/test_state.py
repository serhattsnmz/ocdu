"""Tests for ocdu.state (pinned session ids)."""

from __future__ import annotations
import json
from ocdu.state import pinned_session_ids, toggle_pinned

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

class TestTogglePinned:

    def test_adds_then_removes(self, config_factory):
        cfg = config_factory()
        assert toggle_pinned(cfg, "a") is True
        assert pinned_session_ids(cfg) == {"a"}
        assert toggle_pinned(cfg, "a") is False
        assert pinned_session_ids(cfg) == set()

    def test_appends_new_ids_in_order(self, config_factory):
        cfg = config_factory()
        toggle_pinned(cfg, "a")
        toggle_pinned(cfg, "b")
        toggle_pinned(cfg, "c")
        toggle_pinned(cfg, "a")
        path = cfg.state_dir / "session.json"
        assert json.loads(path.read_text(encoding="utf-8"))["pinned"] == ["b", "c"]

    def test_preserves_other_keys(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, {"pinned": ["a"], "other": {"x": 1}})
        toggle_pinned(cfg, "b")
        data = json.loads((cfg.state_dir / "session.json").read_text(encoding="utf-8"))
        assert data["other"] == {"x": 1}
        assert data["pinned"] == ["a", "b"]

    def test_creates_state_directory(self, config_factory):
        cfg = config_factory()
        assert not cfg.state_dir.exists()
        toggle_pinned(cfg, "a")
        assert (cfg.state_dir / "session.json").is_file()

    def test_malformed_file_starts_empty(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, "{broken")
        assert toggle_pinned(cfg, "a") is True
        assert pinned_session_ids(cfg) == {"a"}

    def test_pinned_not_a_list_is_replaced(self, config_factory):
        cfg = config_factory()
        _write_state(cfg, {"pinned": "abc"})
        assert toggle_pinned(cfg, "a") is True
        assert pinned_session_ids(cfg) == {"a"}
