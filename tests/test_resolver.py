"""Tests for the IgnoreResolver."""

from __future__ import annotations

from pathlib import Path

from ignoretree import IgnoreDecision, IgnoreResolver, PatternSource

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
        assert resolver.is_ignored("README.md") is False
        assert resolver.is_ignored("pyproject.toml") is False

    def test_no_defaults_ignores_nothing(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path)
        assert resolver.is_ignored(".git/config") is False
        assert resolver.is_ignored("module.pyc") is False
        assert resolver.is_ignored("src/main.py") is False


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

    def test_empty_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("main.py") is False

    def test_loads_root_gitignore(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.csv\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("data.csv") is True
        assert resolver.is_ignored("sub/data.csv") is True
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
        assert resolver.is_dir_ignored("src") is False

    def test_prunes_gitignore_dir_pattern(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("build_output/\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_dir_ignored("build_output") is True


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Edge cases."""

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
        assert len(resolver._gitignore_layers) == 1  # no duplicate layers

    def test_trailing_whitespace_in_patterns(self, tmp_path: Path) -> None:
        """Unescaped trailing whitespace doesn't affect matching."""
        (tmp_path / ".gitignore").write_text("*.log   \n  *.pyc\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("debug.log") is True
        assert resolver.is_ignored("module.pyc") is True

    def test_escaped_trailing_space_patterns(self, tmp_path: Path) -> None:
        """Escaped trailing spaces are preserved through reader to resolver."""
        (tmp_path / ".gitignore").write_text("ignoretrailingspace \nnotignoredspace\\ \n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        # Unescaped trailing space is stripped by pathspec — matches without space.
        assert resolver.is_ignored("ignoretrailingspace") is True
        assert resolver.is_ignored("ignoretrailingspace ") is False
        # Escaped trailing space is preserved — matches WITH space only.
        assert resolver.is_ignored("notignoredspace ") is True
        assert resolver.is_ignored("notignoredspace") is False

    def test_negation_with_wildcard_directory(self, tmp_path: Path) -> None:
        """Negation works with wildcard directory patterns."""
        (tmp_path / ".gitignore").write_text("*/backup/*\n!*/backup/backup.sh\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("project/backup/data.zip") is True
        assert resolver.is_ignored("project/backup/backup.sh") is False
        assert resolver.is_ignored("other/backup/old.tar") is True
        assert resolver.is_ignored("other/backup/backup.sh") is False

    def test_directory_negation_with_gitkeep(self, tmp_path: Path) -> None:
        """Complex data directory pattern with directory-only negation.

        Note: git un-ignores directories via ``!data/**/`` but
        GitIgnoreSpec does not honour this negation for directory paths
        ending in ``/``.  We test the actual GitIgnoreSpec behaviour here
        and document the deviation in the git compliance suite.
        """
        (tmp_path / ".gitignore").write_text("data/**\n!data/**/\n!.gitkeep\n!data/raw/*\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        # GitIgnoreSpec does NOT un-ignore directories via !data/**/ —
        # this diverges from git (which does un-ignore them).
        assert resolver.is_ignored("data/raw/") is True
        assert resolver.is_ignored("data/processed/") is True
        # .gitkeep is un-ignored globally.
        assert resolver.is_ignored("data/raw/.gitkeep") is False
        # raw/* is un-ignored.
        assert resolver.is_ignored("data/raw/raw_file.csv") is False
        # processed files remain ignored.
        assert resolver.is_ignored("data/processed/processed_file.csv") is True

    def test_dir_ignored_pruning_caveat(self, tmp_path: Path) -> None:
        """is_dir_ignored returns True even when files inside are re-included.

        Note: git 2.48.1 does NOT allow re-inclusion from excluded parent
        directories (build/keep.txt stays ignored). GitIgnoreSpec diverges
        here — it allows the negation. We document this known deviation.
        """
        (tmp_path / ".gitignore").write_text("build/\n!build/keep.txt\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        # The directory itself matches the ignore pattern.
        assert resolver.is_dir_ignored("build") is True
        # GitIgnoreSpec allows re-inclusion (more permissive than git).
        assert resolver.is_ignored("build/keep.txt") is False
        assert resolver.is_ignored("build/output.o") is True

    def test_wildcard_contents_pattern_no_dir_pruning(self, tmp_path: Path) -> None:
        """folder/* ignores contents but NOT the dir — is_dir_ignored returns False."""
        (tmp_path / ".gitignore").write_text("folder/*\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        # The directory itself does NOT match folder/*.
        assert resolver.is_dir_ignored("folder") is False
        # Files inside are ignored.
        assert resolver.is_ignored("folder/file.txt") is True
        assert resolver.is_ignored("folder/sub/deep.txt") is True

    def test_wildcard_contents_with_negation(self, tmp_path: Path) -> None:
        """folder/* + negation of a direct child correctly un-ignores it."""
        (tmp_path / ".gitignore").write_text("folder/*\n!folder/keep.txt\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_dir_ignored("folder") is False
        assert resolver.is_ignored("folder/file.txt") is True
        assert resolver.is_ignored("folder/keep.txt") is False

    def test_cross_layer_pruning_caveat(self, tmp_path: Path) -> None:
        """Pruning can miss cross-layer negation of an ignored directory."""
        (tmp_path / ".gitignore").write_text("!build/keep.txt\n")
        resolver = IgnoreResolver(tmp_path, default_patterns=["build/"])
        resolver.enter_directory("")
        # Defaults layer ignores build/ — is_dir_ignored returns True.
        assert resolver.is_dir_ignored("build") is True
        # But the gitignore layer un-ignores a file inside.
        assert resolver.is_ignored("build/keep.txt") is False
        assert resolver.is_ignored("build/other.txt") is True


# ---------------------------------------------------------------------------
# explain() source tracking
# ---------------------------------------------------------------------------


class TestExplain:
    """Tests for explain() and explain_dir() source tracking."""

    def test_no_match_returns_not_ignored_no_source(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path)
        decision = resolver.explain("main.py")
        assert decision == IgnoreDecision(ignored=False, source=None)

    def test_default_pattern_source(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(tmp_path, default_patterns=["*.pyc"])
        decision = resolver.explain("module.pyc")
        assert decision.ignored is True
        assert decision.source == PatternSource(file="<defaults>", line=None, pattern="*.pyc")

    def test_info_exclude_source(self, tmp_path: Path) -> None:
        exclude_dir = tmp_path / ".git" / "info"
        exclude_dir.mkdir(parents=True)
        (exclude_dir / "exclude").write_text("*.secret\n")
        resolver = IgnoreResolver(tmp_path)
        decision = resolver.explain("credentials.secret")
        assert decision.ignored is True
        assert decision.source == PatternSource(
            file=".git/info/exclude", line=1, pattern="*.secret"
        )

    def test_gitignore_source(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("# comment\n*.log\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        decision = resolver.explain("debug.log")
        assert decision.ignored is True
        assert decision.source == PatternSource(file=".gitignore", line=2, pattern="*.log")

    def test_nested_gitignore_source(self, tmp_path: Path) -> None:
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / ".gitignore").write_text("*.tmp\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("src")
        decision = resolver.explain("src/debug.tmp")
        assert decision.ignored is True
        assert decision.source == PatternSource(file="src/.gitignore", line=1, pattern="*.tmp")

    def test_custom_file_source(self, tmp_path: Path) -> None:
        (tmp_path / ".myignore").write_text("*.draft\n")
        resolver = IgnoreResolver(tmp_path, custom_ignore_filenames=[".myignore"])
        decision = resolver.explain("notes.draft")
        assert decision.ignored is True
        assert decision.source == PatternSource(file=".myignore", line=1, pattern="*.draft")

    def test_negation_source(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("*.log\n!important.log\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        decision = resolver.explain("important.log")
        assert decision.ignored is False
        assert decision.source == PatternSource(file=".gitignore", line=2, pattern="!important.log")

    def test_higher_layer_wins(self, tmp_path: Path) -> None:
        """Custom layer overrides .gitignore — explain reports the winning source."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / ".myignore").write_text("!*.log\n")
        resolver = IgnoreResolver(tmp_path, custom_ignore_filenames=[".myignore"])
        resolver.enter_directory("")
        decision = resolver.explain("debug.log")
        assert decision.ignored is False
        assert decision.source == PatternSource(file=".myignore", line=1, pattern="!*.log")

    def test_explain_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("build/\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        decision = resolver.explain_dir("build")
        assert decision.ignored is True
        assert decision.source == PatternSource(file=".gitignore", line=1, pattern="build/")

    def test_explain_consistent_with_is_ignored(self, tmp_path: Path) -> None:
        """explain().ignored always matches is_ignored() for the same path."""
        (tmp_path / ".gitignore").write_text("*.log\n!important.log\nbuild/\n")
        resolver = IgnoreResolver(tmp_path, default_patterns=["*.pyc"])
        resolver.enter_directory("")
        for path in ["debug.log", "important.log", "main.py", "module.pyc", "build/"]:
            assert resolver.explain(path).ignored == resolver.is_ignored(path)
