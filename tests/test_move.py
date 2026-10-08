"""Tests for ocdu.move (project-id resolution and session relocation)."""

from __future__ import annotations
import hashlib
import sqlite3
from pathlib import Path
import pytest
import ocdu.move as move_module
from ocdu.db import Database
from ocdu.move import (
    _cached_id,
    _normalize_remote,
    _sha1,
    compute_path,
    descendants,
    move_session,
    resolve_target,
    TargetProject,
)
from tests.factories import ProjectFactory, SessionFactory

class TestSha1:

    def test_mirrors_expected_hash(self):
        assert _sha1("git-remote:github.com/foo/bar") == hashlib.sha1(b"git-remote:github.com/foo/bar").hexdigest()

    def test_length(self):
        assert len(_sha1("x")) == 40

class TestNormalizeRemote:

    @pytest.mark.parametrize("raw", [None, "", "   "])
    def test_empty_inputs(self, raw):
        assert _normalize_remote(raw) is None

    def test_https_with_git_suffix(self):
        assert _normalize_remote("https://github.com/foo/bar.git") == "github.com/foo/bar"

    def test_host_is_lowercased_path_kept(self):
        assert _normalize_remote("https://GitHub.com/Foo/Bar") == "github.com/Foo/Bar"

    def test_scp_like(self):
        assert _normalize_remote("git@github.com:foo/bar.git") == "github.com/foo/bar"

    def test_ssh_scheme(self):
        assert _normalize_remote("ssh://git@github.com/foo/bar.git") == "github.com/foo/bar"

    def test_scp_like_without_user_parsed_as_scheme(self):
        assert _normalize_remote("github.com:foo/bar") is None

    def test_trailing_slash(self):
        assert _normalize_remote("https://host/a/b/") == "host/a/b"

    def test_file_scheme_returns_none(self):
        assert _normalize_remote("file:///c:/repos/x") is None

    def test_windows_path_returns_none(self):
        assert _normalize_remote("C:\\repos\\project") is None

    def test_url_without_hostname_returns_none(self):
        assert _normalize_remote("http:///path") is None

    def test_empty_path_returns_none(self):
        assert _normalize_remote("https://host/") is None

class TestCachedId:

    def test_reads_value(self, tmp_path):
        (tmp_path / "opencode").write_text("cached123", encoding="utf-8")
        assert _cached_id(tmp_path) == "cached123"

    def test_missing_file(self, tmp_path):
        assert _cached_id(tmp_path) is None

    def test_empty_file(self, tmp_path):
        (tmp_path / "opencode").write_text("  ", encoding="utf-8")
        assert _cached_id(tmp_path) is None

    def test_none_git_dir(self):
        assert _cached_id(None) is None

class TestResolveTarget:

    def test_missing_directory_is_global(self, tmp_path):
        project = resolve_target(tmp_path / "nope")
        assert project.project_id == "global"
        assert project.is_git is False

    def test_non_git_directory_is_global(self, tmp_path, monkeypatch):
        monkeypatch.setattr(move_module, "_run_git", lambda *_a, **_k: None)
        project = resolve_target(tmp_path)
        assert project.project_id == "global"
        assert project.is_git is False

    def test_git_remote_hashes_id(self, tmp_path, monkeypatch):
        def fake_run(_directory, args):
            key = " ".join(args)
            if key == "rev-parse --show-toplevel":
                return str(tmp_path)
            if key == "rev-parse --absolute-git-dir":
                return str(tmp_path / ".git")
            if key == "remote get-url origin":
                return "https://github.com/foo/bar.git"
            return None

        monkeypatch.setattr(move_module, "_run_git", fake_run)
        project = resolve_target(tmp_path)
        assert project.project_id == _sha1("git-remote:github.com/foo/bar")
        assert project.is_git is True

    def test_cached_id_used_without_remote(self, tmp_path, monkeypatch):
        (tmp_path / ".git").mkdir()
        (tmp_path / ".git" / "opencode").write_text("cached123", encoding="utf-8")

        def fake_run(_directory, args):
            key = " ".join(args)
            if key == "rev-parse --show-toplevel":
                return str(tmp_path)
            if key == "rev-parse --absolute-git-dir":
                return str(tmp_path / ".git")
            return None

        monkeypatch.setattr(move_module, "_run_git", fake_run)
        assert resolve_target(tmp_path).project_id == "cached123"

    def test_root_commit_used_last(self, tmp_path, monkeypatch):
        def fake_run(_directory, args):
            key = " ".join(args)
            if key == "rev-parse --show-toplevel":
                return str(tmp_path)
            if key == "rev-parse --absolute-git-dir":
                return str(tmp_path / ".git")
            if key == "rev-list --max-parents=0 HEAD":
                return "deadbeef\n"
            return None

        monkeypatch.setattr(move_module, "_run_git", fake_run)
        assert resolve_target(tmp_path).project_id == "deadbeef"

    def test_no_commit_is_global(self, tmp_path, monkeypatch):
        def fake_run(_directory, args):
            key = " ".join(args)
            if key == "rev-parse --show-toplevel":
                return str(tmp_path)
            if key == "rev-parse --absolute-git-dir":
                return str(tmp_path / ".git")
            return None

        monkeypatch.setattr(move_module, "_run_git", fake_run)
        assert resolve_target(tmp_path).project_id == "global"

class TestComputePath:

    def test_nested(self, tmp_path):
        sub = tmp_path / "sub" / "dir"
        assert compute_path(str(tmp_path), str(sub)) == "sub/dir"

    def test_same_directory_is_root(self, tmp_path):
        assert compute_path(str(tmp_path), str(tmp_path)) == ""

    def test_sibling_uses_parent(self, tmp_path):
        assert compute_path(str(tmp_path / "a"), str(tmp_path / "b")) == "../b"

    def test_value_error_falls_back_to_directory(self, tmp_path, monkeypatch):
        monkeypatch.setattr(move_module.os.path, "relpath", lambda *_a: (_ for _ in ()).throw(ValueError()))
        result = compute_path("C:\\a", "D:\\b")
        assert result == "D:/b"

class TestDescendants:

    def test_chain(self, make_db):
        rows = {
            "session": [
                SessionFactory(id="s1", parent_id=None),
                SessionFactory(id="s2", parent_id="s1"),
                SessionFactory(id="s3", parent_id="s2"),
            ]
        }
        db = Database(make_db(rows))
        with db.open() as connection:
            assert descendants(connection, "s1") == ["s2", "s3"]

    def test_no_children(self, make_db):
        rows = {"session": [SessionFactory(id="s1", parent_id=None)]}
        db = Database(make_db(rows))
        with db.open() as connection:
            assert descendants(connection, "s1") == []

class TestMoveSession:

    def _rows(self):
        return {
            "project": [
                ProjectFactory(id="prj0", worktree="/old"),
                ProjectFactory(id="global", worktree="/"),
            ],
            "session": [
                SessionFactory(id="s1", project_id="prj0", directory="/old", path="old"),
                SessionFactory(id="s2", project_id="prj0", parent_id="s1", directory="/old"),
            ],
        }

    def _config(self, config_factory, db_path):
        return config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)

    def test_missing_session_raises(self, make_db, config_factory, tmp_path, monkeypatch):
        monkeypatch.setattr(move_module, "_run_git", lambda *_a, **_k: None)
        db_path = make_db(self._rows())
        with pytest.raises(ValueError):
            move_session(self._config(config_factory, db_path), "ghost", tmp_path)

    def test_missing_target_raises(self, make_db, config_factory, tmp_path, monkeypatch):
        monkeypatch.setattr(move_module, "_run_git", lambda *_a, **_k: None)
        db_path = make_db(self._rows())
        with pytest.raises(FileNotFoundError):
            move_session(self._config(config_factory, db_path), "s1", tmp_path / "missing")

    def test_moves_session_and_children(self, make_db, config_factory, tmp_path, monkeypatch):
        monkeypatch.setattr(move_module, "_run_git", lambda *_a, **_k: None)
        db_path = make_db(self._rows())
        cfg = self._config(config_factory, db_path)
        result = move_session(cfg, "s1", tmp_path)
        assert result.moved_sessions == 2
        assert result.project_id == "global"
        assert result.from_directory == "/old"
        for session_id in ("s1", "s2"):
            connection = sqlite3.connect(str(db_path))
            try:
                row = connection.execute(
                    "SELECT directory, path, project_id FROM session WHERE id = ?", (session_id,)
                ).fetchone()
            finally:
                connection.close()
            assert row[0] == Path(tmp_path).resolve().as_posix()
            assert row[2] == "global"

    def test_force_allows_missing_target(self, make_db, config_factory, tmp_path, monkeypatch):
        monkeypatch.setattr(move_module, "_run_git", lambda *_a, **_k: None)
        db_path = make_db(self._rows())
        result = move_session(self._config(config_factory, db_path), "s1", tmp_path / "ghost", force=True)
        assert result.moved_sessions == 2

    def test_creates_missing_project_row(self, make_db, config_factory, tmp_path, monkeypatch):
        new_project = TargetProject(
            directory=tmp_path, project_id="newproj", worktree=str(tmp_path), is_git=True
        )
        monkeypatch.setattr(move_module, "resolve_target", lambda _target: new_project)
        db_path = make_db(self._rows())
        move_session(self._config(config_factory, db_path), "s1", tmp_path)
        connection = sqlite3.connect(db_path)
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM project WHERE id = 'newproj'"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT project_id FROM session WHERE id = 's1'"
            ).fetchone()[0] == "newproj"
        finally:
            connection.close()
