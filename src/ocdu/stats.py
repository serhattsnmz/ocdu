"""Token and cost statistics across sessions."""

from __future__ import annotations
import sqlite3
from dataclasses import dataclass, field
from .db import Database

@dataclass
class TokenTotals:
    """Aggregate token and cost totals."""

    sessions: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost: float = 0.0

@dataclass
class ModelStat:
    """Token and cost totals for a single model."""

    provider: str
    model: str
    sessions: int
    tokens: int
    cost: float

@dataclass
class DirectoryStat:
    """Token and cost totals for a single working directory."""

    directory: str
    sessions: int
    tokens: int
    cost: float

@dataclass
class DayStat:
    """Token and cost totals for a single day."""

    day: str
    sessions: int
    cost: float

@dataclass
class StatsReport:
    """Combined token and cost report with breakdowns."""

    totals: TokenTotals = field(default_factory=TokenTotals)
    by_model: list[ModelStat] = field(default_factory=list)
    by_directory: list[DirectoryStat] = field(default_factory=list)
    by_day: list[DayStat] = field(default_factory=list)

def _tokens_expr() -> str:
    """Return the SQL expression summing all token buckets."""
    return "COALESCE(tokens_input,0) + COALESCE(tokens_output,0) + COALESCE(tokens_reasoning,0)"

def token_stats(db: Database, connection: sqlite3.Connection) -> StatsReport:
    """Compute token/cost totals and breakdowns by model, directory and day."""
    report = StatsReport()

    row = connection.execute(
        "SELECT COUNT(*), COALESCE(SUM(tokens_input),0), COALESCE(SUM(tokens_output),0), "
        "COALESCE(SUM(cost),0) FROM session"
    ).fetchone()
    report.totals = TokenTotals(
        sessions=int(row[0] or 0),
        tokens_input=int(row[1] or 0),
        tokens_output=int(row[2] or 0),
        cost=float(row[3] or 0.0),
    )

    for provider, model, sessions, tokens, cost in connection.execute(
        f"SELECT COALESCE(json_extract(model,'$.providerID'),'unknown'), "
        f"COALESCE(json_extract(model,'$.id'),'unknown'), COUNT(*), COALESCE(SUM({_tokens_expr()}),0), "
        f"COALESCE(SUM(cost),0) FROM session GROUP BY 1, 2 ORDER BY 4 DESC"
    ):
        report.by_model.append(
            ModelStat(provider or "unknown", model or "unknown", int(sessions), int(tokens), float(cost))
        )

    for directory, sessions, tokens, cost in connection.execute(
        f"SELECT directory, COUNT(*), COALESCE(SUM({_tokens_expr()}),0), COALESCE(SUM(cost),0) "
        f"FROM session GROUP BY directory ORDER BY 3 DESC"
    ):
        report.by_directory.append(DirectoryStat(directory, int(sessions), int(tokens), float(cost)))

    for day, sessions, cost in connection.execute(
        "SELECT date(time_created/1000,'unixepoch') AS d, COUNT(*), COALESCE(SUM(cost),0) "
        "FROM session GROUP BY d ORDER BY d DESC LIMIT 30"
    ):
        report.by_day.append(DayStat(day or "?", int(sessions), float(cost)))

    return report
