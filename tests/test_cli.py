"""Tests for the ocdu command-line interface (__main__)."""

from __future__ import annotations
from pathlib import Path
from types import SimpleNamespace as NS
import pytest
import ocdu.__main__ as cli
import ocdu.tui.app as tui_app
from ocdu.model import BackupResult, PruneResult, VacuumResult
from ocdu.move import TargetProject
from ocdu.opencode import CliResult
from ocdu.safety import SafetyStatus
from tests.factories import EventFactory, MessageFactory, ProjectFactory, SessionFactory

def _fake_backup(*_a, **_k) -> BackupResult:
    return BackupResult(path=Path("/b.zip"), db_bytes=1, total_bytes=2, extra_files=0)

def _rows() -> dict:
    return {
        "project": [ProjectFactory(id="prj0")],
        "session": [SessionFactory(id="ses1", project_id="prj0", title="Hello", directory="/d")],
        "message": [MessageFactory(id="m1", session_id="ses1")],
        "event": [EventFactory(aggregate_id="ses1", data="abcd")],
    }

@pytest.fixture
def cli_env(make_db, config_factory, apply_config):
    def _make(rows: dict | None = None):
        db_path = make_db(_rows() if rows is None else rows)
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)
        apply_config(cfg)
        return cfg, db_path

    return _make

class TestParser:

    def test_version_exits(self):
        with pytest.raises(SystemExit):
            cli._build_parser().parse_args(["--version"])

    def test_no_command_is_none(self):
        assert cli._build_parser().parse_args([]).command is None

    def test_inspection_commands(self):
        parser = cli._build_parser()
        assert parser.parse_args(["footprint"]).command == "footprint"
        assert parser.parse_args(["build-dir"]).command == "build-dir"
        assert parser.parse_args(["dirs", "-n", "5"]).limit == 5
        assert parser.parse_args(["sessions", "--flat"]).flat is True

    def test_maintenance_commands(self):
        parser = cli._build_parser()
        assert parser.parse_args(["prune", "-y", "-b"]).backup is True
        assert parser.parse_args(["vacuum", "-f"]).force is True
        assert parser.parse_args(["clean-logs", "-d", "3", "-y"]).days == 3

    def test_session_commands(self):
        parser = cli._build_parser()
        export = parser.parse_args(["export", "s1", "-f", "json", "--thinking"])
        assert export.format == "json"
        assert export.thinking is True
        move = parser.parse_args(["move", "s1", "/tmp", "-b", "-f"])
        assert move.backup is True and move.force is True

class TestMainDispatch:

    def test_no_command_launches_tui(self, monkeypatch):
        monkeypatch.setattr(tui_app, "run", lambda: None)
        assert cli.main([]) == 0

    def test_missing_database_guard(self, config_factory, apply_config, capsys):
        apply_config(config_factory())
        assert cli.main(["dirs"]) == 2
        assert "database not found" in capsys.readouterr().err

    def test_footprint_exempt_from_guard(self, config_factory, apply_config, capsys):
        apply_config(config_factory())
        assert cli.main(["footprint"]) == 0
        assert "OpenCode data footprint" in capsys.readouterr().out

    def test_build_dir_exempt_from_guard(self, config_factory, apply_config, capsys):
        apply_config(config_factory(DIST_DIR="release"))
        assert cli.main(["build-dir"]) == 0
        assert capsys.readouterr().out.strip() == "release"

    def test_timing_shown_for_dirs_not_footprint(self, cli_env, capsys):
        cli_env()
        cli.main(["dirs"])
        assert "s)" in capsys.readouterr().out

class TestBuildDirAndFootprint:

    def test_build_dir(self, config_factory, apply_config, capsys):
        apply_config(config_factory(DIST_DIR="out"))
        assert cli._cmd_build_dir(NS()) == 0
        assert capsys.readouterr().out.strip() == "out"

    def test_footprint(self, cli_env, capsys):
        cli_env()
        assert cli._cmd_footprint(NS()) == 0
        out = capsys.readouterr().out
        assert "TOTAL:" in out

class TestListCommands:

    def test_dirs_limit_truncates(self, cli_env, capsys):
        cli_env()
        cli._cmd_dirs(NS(limit=0))
        assert "Session data by directory" in capsys.readouterr().out
        cli._cmd_dirs(NS(limit=1))
        assert "directories, total" in capsys.readouterr().out

    def test_sessions_flat_and_limit(self, cli_env, capsys):
        cli_env()
        cli._cmd_sessions(NS(limit=0, flat=False))
        assert "root sessions (children aggregated)" in capsys.readouterr().out
        cli._cmd_sessions(NS(limit=0, flat=True))
        assert "all sessions (flat)" in capsys.readouterr().out

    def test_orphans_lists_files_and_remainder(self, make_db, config_factory, apply_config, capsys):
        rows = _rows()
        db_path = make_db(rows)
        cfg = config_factory(OPENCODE_DATA_DIR=str(db_path.parent), OPENCODE_DB_FILE=db_path.name)
        apply_config(cfg)
        diff_dir = cfg.data_dir / "storage" / "session_diff"
        diff_dir.mkdir(parents=True)
        for index in range(22):
            (diff_dir / f"ghost{index}.json").write_text("x", encoding="utf-8")
        assert cli._cmd_orphans(NS()) == 0
        out = capsys.readouterr().out
        assert "and 2 more" in out

class TestSessionLookup:

    def test_found(self, cli_env):
        cli_env()
        title, directory, total = cli._session_lookup("ses1")
        assert title == "Hello"
        assert directory == "/d"
        assert total >= 4

    def test_missing(self, cli_env):
        cli_env()
        assert cli._session_lookup("ghost") is None

class TestDeleteCommand:

    def test_dry_run(self, cli_env, capsys, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "delete_session", lambda *_a, **_k: pytest.fail("should not delete"))
        assert cli._cmd_delete(NS(session_id="ses1", yes=False)) == 0
        assert "Dry-run" in capsys.readouterr().out

    def test_missing_session(self, cli_env, capsys):
        cli_env()
        assert cli._cmd_delete(NS(session_id="ghost", yes=False)) == 2
        assert "session not found" in capsys.readouterr().err

    def test_success(self, cli_env, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "delete_session", lambda *_a, **_k: CliResult([], 0, "", ""))
        assert cli._cmd_delete(NS(session_id="ses1", yes=True)) == 0

    def test_failure(self, cli_env, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "delete_session", lambda *_a, **_k: CliResult([], 1, "", "boom"))
        assert cli._cmd_delete(NS(session_id="ses1", yes=True)) == 1

class TestPruneCommand:

    def test_dry_run(self, cli_env, capsys):
        cli_env()
        assert cli._cmd_prune(NS(yes=False, backup=False)) == 0
        assert "Dry-run" in capsys.readouterr().out

    def test_confirmed_with_backup(self, cli_env, capsys, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "prune", lambda *_a, **_k: PruneResult(orphan_event_sequences=1, orphan_event_bytes=4))
        monkeypatch.setattr(cli, "create_backup", _fake_backup)
        assert cli._cmd_prune(NS(yes=True, backup=True)) == 0
        out = capsys.readouterr().out
        assert "Backup:" in out
        assert "Pruned:" in out

class TestVacuumCommand:

    def test_dry_run(self, cli_env, capsys, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "vacuum_dry_run", lambda *_a: VacuumResult(before_bytes=100, after_bytes=40))
        assert cli._cmd_vacuum(NS(yes=False, force=False)) == 0
        assert "reclaimable" in capsys.readouterr().out

    def test_refuses_when_unsafe(self, cli_env, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "vacuum_dry_run", lambda *_a: VacuumResult(before_bytes=100, after_bytes=40))
        monkeypatch.setattr(cli, "probe", lambda *_a: SafetyStatus(db_in_use=True, opencode_processes=[]))
        assert cli._cmd_vacuum(NS(yes=True, force=False)) == 1

    def test_force_runs(self, cli_env, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "vacuum_dry_run", lambda *_a: VacuumResult(before_bytes=100, after_bytes=40))
        monkeypatch.setattr(cli, "probe", lambda *_a: SafetyStatus(db_in_use=True, opencode_processes=[]))
        monkeypatch.setattr(cli, "vacuum", lambda *_a: VacuumResult(before_bytes=100, after_bytes=40))
        assert cli._cmd_vacuum(NS(yes=True, force=True)) == 0

class TestOtherMaintenanceCommands:

    def test_backup(self, cli_env, capsys, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "create_backup", _fake_backup)
        monkeypatch.setattr(cli, "list_backups", lambda *_a: [Path("/b.zip")])
        monkeypatch.setattr(cli, "backup_dir_size", lambda *_a: 2)
        assert cli._cmd_backup(NS()) == 0
        assert "Backup created" in capsys.readouterr().out

    def test_check(self, cli_env, capsys, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "integrity_check", lambda *_a: "ok")
        monkeypatch.setattr(cli, "probe", lambda *_a: SafetyStatus(False, []))
        assert cli._cmd_check(NS()) == 0
        assert "integrity_check: ok" in capsys.readouterr().out

    def test_checkpoint(self, cli_env, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "checkpoint", lambda *_a: VacuumResult(before_bytes=10, after_bytes=5))
        assert cli._cmd_checkpoint(NS()) == 0

    def test_clean_logs_negative_days(self, cli_env, capsys):
        cli_env()
        assert cli._cmd_clean_logs(NS(days=-1, yes=False)) == 2
        assert "--days must be >= 0" in capsys.readouterr().err

    def test_clean_logs_dry_run(self, cli_env, capsys):
        cli_env()
        assert cli._cmd_clean_logs(NS(days=30, yes=False)) == 0
        assert "Log cleanup" in capsys.readouterr().out

    def test_stats(self, cli_env, capsys):
        cli_env()
        assert cli._cmd_stats(NS()) == 0
        assert "Token & cost statistics" in capsys.readouterr().out

class TestSessionCommands:

    def test_rename_success_and_missing(self, cli_env, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "set_title", lambda *_a: True)
        assert cli._cmd_rename(NS(session_id="ses1", title="New")) == 0
        monkeypatch.setattr(cli, "set_title", lambda *_a: False)
        assert cli._cmd_rename(NS(session_id="ghost", title="New")) == 2

    def _project(self, tmp_path, project_id="global"):
        return TargetProject(directory=tmp_path, project_id=project_id, worktree=str(tmp_path), is_git=False)

    def test_move_missing_session(self, cli_env, tmp_path, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "resolve_target", lambda _t: self._project(tmp_path))
        assert cli._cmd_move(NS(session_id="ghost", directory=str(tmp_path), yes=False, backup=False, force=False)) == 2

    def test_move_missing_target(self, cli_env, tmp_path, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "resolve_target", lambda _t: self._project(tmp_path / "nope"))
        args = NS(session_id="ses1", directory=str(tmp_path / "nope"), yes=False, backup=False, force=False)
        assert cli._cmd_move(args) == 1

    def test_move_dry_run(self, cli_env, tmp_path, monkeypatch, capsys):
        cli_env()
        monkeypatch.setattr(cli, "resolve_target", lambda _t: self._project(tmp_path))
        args = NS(session_id="ses1", directory=str(tmp_path), yes=False, backup=False, force=False)
        assert cli._cmd_move(args) == 0
        assert "Dry-run" in capsys.readouterr().out

    def test_move_confirmed(self, cli_env, tmp_path, monkeypatch):
        cli_env()
        monkeypatch.setattr(cli, "resolve_target", lambda _t: self._project(tmp_path))
        from ocdu.move import MoveResult
        fake = MoveResult(
            session_id="ses1", from_directory="/old", to_directory=str(tmp_path),
            project_id="global", path="", moved_sessions=1,
        )
        monkeypatch.setattr(cli, "move_session", lambda *_a, **_k: fake)
        args = NS(session_id="ses1", directory=str(tmp_path), yes=True, backup=False, force=False)
        assert cli._cmd_move(args) == 0

class TestExport:

    def test_resolve_dest_directory(self, tmp_path):
        assert cli._resolve_dest(NS(out=str(tmp_path)), "T", "s1", "md") == tmp_path / "T.md"

    def test_resolve_dest_file(self, tmp_path):
        target = tmp_path / "x.json"
        assert cli._resolve_dest(NS(out=str(target)), "T", "s1", "json") == target

    def test_resolve_dest_defaults_to_cwd(self):
        assert cli._resolve_dest(NS(out=None), "T", "s1", "md") == Path.cwd() / "T.md"

    def test_export_markdown(self, cli_env, tmp_path, monkeypatch, capsys):
        cli_env()
        dest = tmp_path / "out.md"
        monkeypatch.setattr(cli, "export_markdown", lambda *_a, **_k: dest)
        args = NS(
            session_id="ses1", format="md", out=str(dest),
            thinking=False, no_tool_details=False, no_metadata=False,
        )
        assert cli._cmd_export(args) == 0
        assert "Exported:" in capsys.readouterr().out

    def test_export_missing_session(self, cli_env, capsys):
        cli_env()
        args = NS(session_id="ghost", format="md", out=None, thinking=False, no_tool_details=False, no_metadata=False)
        assert cli._cmd_export(args) == 2
