"""Tests for the ignore file reader."""

from __future__ import annotations

from pathlib import Path

from ignoretree.reader import read_ignore_file


class TestReadIgnoreFile:
    """Tests for the read_ignore_file function."""

    def test_reads_patterns(self, tmp_path: Path) -> None:
        f = tmp_path / ".gitignore"
        f.write_text("*.pyc\n__pycache__/\ndist/\n")
        patterns, sources = read_ignore_file(f)
        assert patterns == ["*.pyc", "__pycache__/", "dist/"]
        assert len(sources) == 3

    def test_strips_leading_whitespace_only(self, tmp_path: Path) -> None:
        """Leading whitespace is stripped; trailing is preserved for pathspec."""
        f = tmp_path / ".gitignore"
        f.write_text("  *.pyc  \n  dist/  \n")
        patterns, _ = read_ignore_file(f)
        assert patterns == ["*.pyc  ", "dist/  "]

    def test_skips_comments(self, tmp_path: Path) -> None:
        f = tmp_path / ".gitignore"
        f.write_text("# comment\n*.pyc\n# another\n")
        patterns, _ = read_ignore_file(f)
        assert patterns == ["*.pyc"]

    def test_skips_blank_lines(self, tmp_path: Path) -> None:
        f = tmp_path / ".gitignore"
        f.write_text("\n*.pyc\n\n\ndist/\n")
        patterns, _ = read_ignore_file(f)
        assert patterns == ["*.pyc", "dist/"]

    def test_preserves_negation(self, tmp_path: Path) -> None:
        f = tmp_path / ".gitignore"
        f.write_text("*.log\n!important.log\n")
        patterns, _ = read_ignore_file(f)
        assert patterns == ["*.log", "!important.log"]

    def test_returns_empty_for_missing_file(self, tmp_path: Path) -> None:
        patterns, sources = read_ignore_file(tmp_path / "nonexistent")
        assert patterns == []
        assert sources == []

    def test_returns_empty_on_unreadable(self, tmp_path: Path) -> None:
        f = tmp_path / ".gitignore"
        f.write_text("*.pyc")
        f.chmod(0o000)
        patterns, sources = read_ignore_file(f)
        f.chmod(0o644)  # restore for cleanup
        assert patterns == []
        assert sources == []

    def test_tracks_pattern_sources(self, tmp_path: Path) -> None:
        """Each pattern has a corresponding PatternSource with file, line, and text."""
        f = tmp_path / ".gitignore"
        f.write_text("# comment\n*.pyc\n\ndist/\n")
        patterns, sources = read_ignore_file(f)

        assert len(patterns) == len(sources)
        # *.pyc is on line 2, dist/ is on line 4 (blank line 3 skipped).
        assert sources[0].file == ".gitignore"
        assert sources[0].line == 2
        assert sources[0].pattern == "*.pyc"
        assert sources[1].line == 4
        assert sources[1].pattern == "dist/"

    def test_custom_source_label(self, tmp_path: Path) -> None:
        f = tmp_path / ".gitignore"
        f.write_text("*.log\n")
        _, sources = read_ignore_file(f, source_label="src/.gitignore")
        assert sources[0].file == "src/.gitignore"

    def test_preserves_escaped_trailing_space(self, tmp_path: Path) -> None:
        """Backslash-escaped trailing spaces are preserved for pathspec."""
        f = tmp_path / ".gitignore"
        f.write_text("foo\\ \n")
        patterns, _ = read_ignore_file(f)
        assert patterns == ["foo\\ "]
