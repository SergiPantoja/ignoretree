"""Tests for the IgnoreResolver."""

from __future__ import annotations

from pathlib import Path

from ignoretree import IgnoreResolver

# ---------------------------------------------------------------------------
# Default patterns layer
# ---------------------------------------------------------------------------


class TestDefaults:
    """Tests for the default_patterns layer."""

    def test_matches_default_patterns(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path, default_patterns=[".git/", "*.pyc", "__pycache__/"])
        assert resolver.is_ignored(".git/config") is True
        assert resolver.is_ignored(".git/HEAD") is True
        assert resolver.is_ignored("module.pyc") is True

    def test_no_defaults_ignores_nothing(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path)
        assert resolver.is_ignored(".git/config") is False
        assert resolver.is_ignored("module.pyc") is False
        assert resolver.is_ignored("src/main.py") is False

    def test_does_not_ignore_unmatched(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path, default_patterns=["*.pyc", "__pycache__/"])
        assert resolver.is_ignored("src/main.py") is False
        assert resolver.is_ignored("README.md") is False
        assert resolver.is_ignored("pyproject.toml") is False


# ---------------------------------------------------------------------------
# .git/info/exclude layer
# ---------------------------------------------------------------------------


class TestInfoExclude:
    """Tests for .git/info/exclude support."""

    def test_loads_info_exclude(self, tmp_path: Path) -> None:
        exclude_dir = tmp_path / ".git" / "info"
        exclude_dir.mkdir(parents=True)
        (exclude_dir / "exclude").write_text("*.secret\n")
        resolver = IgnoreResolver(tmp_path)
        assert resolver.is_ignored("credentials.secret") is True
        assert resolver.is_ignored("main.py") is False

    def test_gitignore_overrides_info_exclude(self, tmp_path: Path) -> None:
        """A .gitignore negation can un-ignore what .git/info/exclude ignored."""
        exclude_dir = tmp_path / ".git" / "info"
        exclude_dir.mkdir(parents=True)
        (exclude_dir / "exclude").write_text("*.secret\n")
        (tmp_path / ".gitignore").write_text("!important.secret\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        # .gitignore (layer 3) overrides .git/info/exclude (layer 2).
        assert resolver.is_ignored("credentials.secret") is True
        assert resolver.is_ignored("important.secret") is False

    def test_missing_info_exclude_no_error(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path)
        assert resolver.is_ignored("main.py") is False


# ---------------------------------------------------------------------------
# .gitignore loading & scoping
# ---------------------------------------------------------------------------


class TestGitignore:
    """Tests for .gitignore loading and nested scoping."""

    def test_loads_root_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.csv\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("data.csv") is True
        assert resolver.is_ignored("sub/data.csv") is True

    def test_gitignore_does_not_affect_unmatched(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.csv\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("main.py") is False

    def test_nested_gitignore_scoping(self, tmp_path: Path) -> None:
        """A .gitignore in src/ only affects files under src/."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / ".gitignore").write_text("*.tmp\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        resolver.enter_directory("src")
        assert resolver.is_ignored("src/debug.tmp") is True
        assert resolver.is_ignored("debug.tmp") is False

    def test_nested_gitignore_deep(self, tmp_path: Path) -> None:
        """Multiple nested .gitignore files accumulate correctly."""
        (tmp_path / "src" / "lib").mkdir(parents=True)
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "src" / ".gitignore").write_text("*.bak\n")
        (tmp_path / "src" / "lib" / ".gitignore").write_text("*.dump\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        resolver.enter_directory("src")
        resolver.enter_directory("src/lib")

        # Root .gitignore: *.log applies everywhere.
        assert resolver.is_ignored("app.log") is True
        assert resolver.is_ignored("src/app.log") is True
        assert resolver.is_ignored("src/lib/app.log") is True

        # src/.gitignore: *.bak applies under src/ only.
        assert resolver.is_ignored("src/file.bak") is True
        assert resolver.is_ignored("src/lib/file.bak") is True
        assert resolver.is_ignored("file.bak") is False

        # src/lib/.gitignore: *.dump applies under src/lib/ only.
        assert resolver.is_ignored("src/lib/core.dump") is True
        assert resolver.is_ignored("src/core.dump") is False

    def test_missing_gitignore_no_error(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("main.py") is False


# ---------------------------------------------------------------------------
# Negation patterns
# ---------------------------------------------------------------------------


class TestNegation:
    """Tests for negation within and across layers."""

    def test_negation_within_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n!important.log\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("debug.log") is True
        assert resolver.is_ignored("important.log") is False

    def test_negation_across_gitignore_layers(self, tmp_path: Path) -> None:
        """A deeper .gitignore can un-ignore what a shallower one ignored."""
        (tmp_path / "src").mkdir()
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "src" / ".gitignore").write_text("!audit.log\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        resolver.enter_directory("src")

        assert resolver.is_ignored("debug.log") is True
        assert resolver.is_ignored("src/audit.log") is False
        assert resolver.is_ignored("src/debug.log") is True

    def test_custom_negation_overrides_gitignore(self, tmp_path: Path) -> None:
        """Custom ignore file can un-ignore .gitignore patterns."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / ".myignore").write_text("!*.log\n")
        resolver = IgnoreResolver(tmp_path, custom_ignore_filenames=[".myignore"])
        resolver.enter_directory("")
        assert resolver.is_ignored("debug.log") is False

    def test_default_negated_by_gitignore(self, tmp_path: Path) -> None:
        """A .gitignore negation overrides a default pattern."""
        (tmp_path / ".gitignore").write_text("!important.pyc\n")
        resolver = IgnoreResolver(tmp_path, default_patterns=["*.pyc"])
        resolver.enter_directory("")
        assert resolver.is_ignored("module.pyc") is True
        assert resolver.is_ignored("important.pyc") is False


# ---------------------------------------------------------------------------
# Custom ignore files
# ---------------------------------------------------------------------------


class TestCustom:
    """Tests for custom ignore file handling."""

    def test_custom_ignore_file(self, tmp_path: Path) -> None:
        (tmp_path / ".myignore").write_text("*.draft\n")
        resolver = IgnoreResolver(tmp_path, custom_ignore_filenames=[".myignore"])
        assert resolver.is_ignored("notes.draft") is True

    def test_multiple_custom_files(self, tmp_path: Path) -> None:
        (tmp_path / ".ignore1").write_text("*.tmp\n")
        (tmp_path / ".ignore2").write_text("*.draft\n")
        resolver = IgnoreResolver(
            tmp_path,
            custom_ignore_filenames=[".ignore1", ".ignore2"],
        )
        assert resolver.is_ignored("file.tmp") is True
        assert resolver.is_ignored("file.draft") is True

    def test_custom_overrides_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / ".myignore").write_text("!*.log\n")
        resolver = IgnoreResolver(tmp_path, custom_ignore_filenames=[".myignore"])
        resolver.enter_directory("")
        assert resolver.is_ignored("app.log") is False

    def test_missing_custom_file_no_error(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path, custom_ignore_filenames=[".nonexistent"])
        assert resolver.is_ignored("main.py") is False


# ---------------------------------------------------------------------------
# Directory pruning
# ---------------------------------------------------------------------------


class TestDirPruning:
    """Tests for is_dir_ignored used for directory pruning."""

    def test_prunes_matching_default_directory(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path, default_patterns=["__pycache__/"])
        assert resolver.is_dir_ignored("__pycache__") is True
        assert resolver.is_dir_ignored("src/__pycache__") is True

    def test_does_not_prune_unmatched_dirs(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path, default_patterns=["__pycache__/"])
        assert resolver.is_dir_ignored("src") is False
        assert resolver.is_dir_ignored("tests") is False
        assert resolver.is_dir_ignored("docs") is False

    def test_prunes_gitignore_dir_pattern(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("build_output/\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_dir_ignored("build_output") is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases and boundary conditions."""

    def test_comment_only_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("# just a comment\n#main.py\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("main.py") is False

    def test_enter_directory_idempotent(self, tmp_path: Path) -> None:
        """Entering the same directory twice doesn't cause issues."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        resolver.enter_directory("")
        assert resolver.is_ignored("debug.log") is True
        assert resolver.is_ignored("main.py") is False
        assert len(resolver._gitignore_layers) == 1  # No duplicate layers added

    def test_trailing_whitespace_in_patterns(self, tmp_path: Path) -> None:
        """Trailing whitespace in pattern files doesn't affect matching."""
        (tmp_path / ".gitignore").write_text("*.log   \n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("debug.log") is True

    def test_empty_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("main.py") is False
