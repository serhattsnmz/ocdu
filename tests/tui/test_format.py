"""Tests for ocdu.tui.format (cell formatting helpers)."""

from __future__ import annotations
from pathlib import Path
from ocdu.tui.format import (
    cost_text,
    count_text,
    header_text,
    shorten_home,
    size_markup,
    size_text,
    token_text,
)

class TestHeaderText:

    def test_right_aligned(self):
        assert header_text("Size", 9).plain == "     Size"

class TestSizeText:

    def test_width_padded(self):
        assert size_text(0, 9).plain == "0 B".rjust(9)

    def test_gb_is_red(self):
        text = size_text(1024**3)
        assert any(span.style == "red" for span in text.spans)

    def test_mb_is_yellow(self):
        text = size_text(1024**2)
        assert any(span.style == "yellow" for span in text.spans)

    def test_small_is_unstyled(self):
        assert size_text(10).spans == []

class TestCountCostToken:

    def test_count_text(self):
        assert count_text(5, 4).plain == "   5"

    def test_cost_text(self):
        assert cost_text(1234.5, 9).plain == "$1,234.50"

    def test_token_text(self):
        assert token_text(1000, 8).plain == "   1,000"

class TestSizeMarkup:

    def test_gb(self):
        assert size_markup(1024**3) == "[red]1.0 GB[/]"

    def test_mb(self):
        assert size_markup(1024**2) == "[yellow]1.0 MB[/]"

    def test_small(self):
        assert size_markup(10) == "10 B"

class TestShortenHome:

    def test_home_exact(self, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: Path("/home/user")))
        assert shorten_home("/home/user") == "~"

    def test_home_subpath(self, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: Path("/home/user")))
        assert shorten_home("/home/user/projects") == "~/projects"

    def test_other_path_unchanged(self, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: Path("/home/user")))
        assert shorten_home("/var/log") == "/var/log"

    def test_windows_separators(self, monkeypatch):
        monkeypatch.setattr(Path, "home", classmethod(lambda _cls: Path("C:/Users/user")))
        assert shorten_home("C:\\Users\\user\\docs") == "~/docs"
