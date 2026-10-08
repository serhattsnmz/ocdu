"""Tests for ocdu.stats (token and cost statistics)."""

from __future__ import annotations
import re
from ocdu.db import Database
from ocdu.stats import token_stats
from tests.factories import ProjectFactory, SessionFactory

def _rows() -> dict:
    return {
        "project": [ProjectFactory(id="prj0")],
        "session": [
            SessionFactory(
                id="s1", project_id="prj0", model='{"providerID": "anthropic", "id": "claude"}',
                cost=1.5, tokens_input=10, tokens_output=5, tokens_reasoning=2,
                directory="/a", time_created=1_700_000_000_000,
            ),
            SessionFactory(
                id="s2", project_id="prj0", model=None,
                cost=0.5, tokens_input=1, tokens_output=1, tokens_reasoning=0,
                directory="/a", time_created=1_700_000_000_000,
            ),
            SessionFactory(
                id="s3", project_id="prj0", model="{}",
                cost=0.0, tokens_input=0, tokens_output=0, tokens_reasoning=0,
                directory="/b", time_created=1_700_086_400_000,
            ),
        ],
    }

def _report(make_db) -> object:
    db = Database(make_db(_rows()))
    with db.open() as connection:
        return token_stats(db, connection)

class TestTokenStats:

    def test_totals(self, make_db):
        report = _report(make_db)
        assert report.totals.sessions == 3
        assert report.totals.tokens_input == 11
        assert report.totals.tokens_output == 6
        assert report.totals.cost == 2.0

    def test_by_model_includes_reasoning(self, make_db):
        report = _report(make_db)
        top = report.by_model[0]
        assert (top.provider, top.model) == ("anthropic", "claude")
        assert top.tokens == 17
        assert top.sessions == 1

    def test_null_and_empty_model_grouped_as_unknown(self, make_db):
        report = _report(make_db)
        unknown = [stat for stat in report.by_model if stat.provider == "unknown" and stat.model == "unknown"]
        assert len(unknown) == 1
        assert unknown[0].sessions == 2

    def test_by_directory(self, make_db):
        report = _report(make_db)
        by_dir = {stat.directory: stat for stat in report.by_directory}
        assert by_dir["/a"].tokens == 19
        assert by_dir["/b"].tokens == 0

    def test_by_day(self, make_db):
        report = _report(make_db)
        assert len(report.by_day) == 2
        assert all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", stat.day) for stat in report.by_day)
