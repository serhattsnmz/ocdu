"""Tests for ocdu.paths (tracked data roots)."""

from __future__ import annotations
from pathlib import Path
from ocdu.model import CATEGORY_BACKUP, CATEGORY_INFO, CATEGORY_LOCKED, CATEGORY_MANAGED
from ocdu.paths import build_roots

EXPECTED_KEYS = [
    "database",
    "session_diff",
    "backups",
    "log",
    "snapshot",
    "tool_output",
    "repos",
    "state",
    "cache",
    "config",
]

class TestBuildRoots:

    def test_order_and_keys(self, config_factory):
        roots = build_roots(config_factory())
        assert [root.key for root in roots] == EXPECTED_KEYS

    def test_categories(self, config_factory):
        roots = {root.key: root for root in build_roots(config_factory())}
        assert roots["database"].category == CATEGORY_MANAGED
        assert roots["session_diff"].category == CATEGORY_MANAGED
        assert roots["log"].category == CATEGORY_MANAGED
        assert roots["backups"].category == CATEGORY_BACKUP
        assert roots["snapshot"].category == CATEGORY_INFO
        assert roots["tool_output"].category == CATEGORY_INFO
        assert roots["repos"].category == CATEGORY_INFO
        assert roots["state"].category == CATEGORY_LOCKED
        assert roots["cache"].category == CATEGORY_LOCKED
        assert roots["config"].category == CATEGORY_LOCKED

    def test_database_companions(self, config_factory):
        roots = {root.key: root for root in build_roots(config_factory())}
        database = roots["database"]
        assert database.companions == [
            Path(str(database.path) + "-wal"),
            Path(str(database.path) + "-shm"),
        ]

    def test_backup_note_mentions_keep(self, config_factory):
        roots = {root.key: root for root in build_roots(config_factory(BACKUP_KEEP="7"))}
        assert "keep 7" in roots["backups"].note

    def test_paths_derive_from_custom_data_dir(self, config_factory):
        cfg = config_factory(OPENCODE_DATA_DIR="/custom/data")
        roots = {root.key: root for root in build_roots(cfg)}
        assert roots["database"].path == Path("/custom/data/opencode.db")
        assert roots["session_diff"].path == Path("/custom/data/storage/session_diff")
        assert roots["log"].path == Path("/custom/data/log")

    def test_locked_roots_use_configured_dirs(self, config_factory):
        cfg = config_factory(OPENCODE_STATE_DIR="/s", OPENCODE_CACHE_DIR="/c", OPENCODE_CONFIG_DIR="/k")
        roots = {root.key: root for root in build_roots(cfg)}
        assert roots["state"].path == Path("/s")
        assert roots["cache"].path == Path("/c")
        assert roots["config"].path == Path("/k")
