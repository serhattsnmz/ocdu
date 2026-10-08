"""Tests for ocdu.util (formatting and filesystem helpers)."""

from __future__ import annotations
import os
from datetime import datetime
from pathlib import Path
import pytest
from ocdu.util import (
    dir_size,
    file_size,
    format_datetime,
    format_day,
    format_time,
    human_size,
    sanitize_text,
    single_line,
    strip_control,
)

class TestHumanSize:

    def test_zero(self):
        assert human_size(0) == "0 B"

    def test_bytes_below_kb(self):
        assert human_size(512) == "512 B"
        assert human_size(1023) == "1023 B"

    def test_exact_kb_boundary(self):
        assert human_size(1024) == "1.0 KB"

    def test_fractional_kb(self):
        assert human_size(1536) == "1.5 KB"

    def test_unit_promotion(self):
        assert human_size(1024**2) == "1.0 MB"
        assert human_size(1024**3) == "1.0 GB"
        assert human_size(1024**4) == "1.0 TB"
        assert human_size(1024**5) == "1.0 PB"

    def test_beyond_last_unit_stays_pb(self):
        assert human_size(1024**6) == "1024.0 PB"

    def test_negative(self):
        assert human_size(-512) == "-512 B"

    def test_precision(self):
        assert human_size(1536, 0) == "2 KB"
        assert human_size(1024, 3) == "1.000 KB"

class TestDirSize:

    def test_single_file(self, tmp_path):
        target = tmp_path / "a.bin"
        target.write_bytes(b"x" * 10)
        assert dir_size(target) == (10, 1)

    def test_nested_directory(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "a.bin").write_bytes(b"x" * 3)
        (tmp_path / "sub" / "b.bin").write_bytes(b"y" * 4)
        (tmp_path / "sub" / "deep").mkdir()
        (tmp_path / "sub" / "deep" / "c.bin").write_bytes(b"z" * 5)
        assert dir_size(tmp_path) == (12, 3)

    def test_missing_path(self, tmp_path):
        assert dir_size(tmp_path / "nope") == (0, 0)

    def test_empty_directory(self, tmp_path):
        assert dir_size(tmp_path) == (0, 0)

    def test_directory_of_only_subdirs(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b").mkdir()
        assert dir_size(tmp_path) == (0, 0)

    def test_symlinked_directory_not_followed(self, tmp_path):
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "big.bin").write_bytes(b"x" * 100)
        root = tmp_path / "root"
        root.mkdir()
        (root / "small.bin").write_bytes(b"x" * 1)
        link = root / "link"
        try:
            os.symlink(outside, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform")
        assert dir_size(root) == (1, 1)

    def test_stat_error_returns_zero(self, tmp_path, monkeypatch):
        target = tmp_path / "a.bin"
        target.write_bytes(b"x" * 4)

        def _boom(_self):
            raise OSError("denied")

        monkeypatch.setattr(Path, "is_file", _boom)
        assert dir_size(target) == (0, 0)


class TestFileSize:

    def test_existing_file(self, tmp_path):
        target = tmp_path / "f.bin"
        target.write_bytes(b"x" * 5)
        assert file_size(target) == 5

    def test_missing_file(self, tmp_path):
        assert file_size(tmp_path / "nope") == 0

    def test_directory_returns_stat_size(self, tmp_path):
        assert file_size(tmp_path) == tmp_path.stat().st_size

class TestFormatDatetime:

    def test_basic(self):
        assert format_datetime(datetime(2024, 1, 2, 3, 4)) == "02.01.2024 03:04"

    def test_midnight_single_digits(self):
        assert format_datetime(datetime(2024, 12, 31, 0, 0)) == "31.12.2024 00:00"

class TestFormatTime:

    def test_none_and_zero(self):
        assert format_time(None) == "-"
        assert format_time(0) == "-"

    def test_valid_milliseconds(self):
        epoch_ms = 1_700_000_000_000
        expected = format_datetime(datetime.fromtimestamp(epoch_ms / 1000))
        assert format_time(epoch_ms) == expected

    def test_out_of_range(self):
        assert format_time(10**18) == "-"

class TestFormatDay:

    def test_valid(self):
        assert format_day("2024-01-02") == "02.01.2024"

    def test_invalid_passthrough(self):
        assert format_day("not-a-date") == "not-a-date"

    def test_none_passthrough(self):
        assert format_day(None) is None

class TestTextSanitising:

    def test_strip_control_removes_all_controls(self):
        assert strip_control("a\x00b\nc\td\x7f") == "abcd"

    def test_sanitize_keeps_newline_and_tab(self):
        assert sanitize_text("a\nb\tc\x00d\x7f") == "a\nb\tcd"

    def test_sanitize_removes_vertical_tab(self):
        assert sanitize_text("a\x0bb") == "ab"

    def test_single_line_collapses_whitespace(self):
        assert single_line("a\n\n  b\tc ") == "a b c"

    def test_single_line_empty(self):
        assert single_line("") == ""

    def test_path_type_input(self, tmp_path):
        assert isinstance(strip_control(str(Path(tmp_path))), str)
