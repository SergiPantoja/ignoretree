"""Tests for the IgnoreResolver."""

from __future__ import annotations

from itertools import permutations
from pathlib import Path
from unittest.mock import patch

from ignoretree import IgnoreDecision, IgnoreResolver, PatternSource
from ignoretree.reader import read_ignore_file

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

    def test_malformed_defaults_are_no_ops(self, tmp_path: Path) -> None:
        resolver = IgnoreResolver(
            tmp_path,
            default_patterns=["!", "trailing\\", "[z-a]", "/", "*.log"],
        )

        assert resolver.explain("debug.log") == IgnoreDecision(
            ignored=True,
            source=PatternSource(file="<defaults>", line=None, pattern="*.log"),
        )
        assert resolver.is_ignored("main.py") is False


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

    def test_each_custom_file_filters_malformed_patterns(self, tmp_path: Path) -> None:
        (tmp_path / ".first").write_text("# comment\n!\n[z-a]\n*.tmp\n")
        (tmp_path / ".second").write_text("trailing\\\n/\n*.draft\n")
        resolver = IgnoreResolver(
            tmp_path,
            custom_ignore_filenames=[".first", ".second"],
        )

        assert resolver.explain("file.tmp") == IgnoreDecision(
            ignored=True,
            source=PatternSource(file=".first", line=4, pattern="*.tmp"),
        )
        assert resolver.explain("file.draft") == IgnoreDecision(
            ignored=True,
            source=PatternSource(file=".second", line=3, pattern="*.draft"),
        )
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

    def test_significant_leading_and_ignored_trailing_whitespace(self, tmp_path: Path) -> None:
        """Git ignores unescaped trailing spaces but preserves leading spaces."""
        (tmp_path / ".gitignore").write_text("*.log   \n  *.pyc\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.enter_directory("")
        assert resolver.is_ignored("debug.log") is True
        assert resolver.is_ignored("module.pyc") is False
        assert resolver.is_ignored("  module.pyc") is True

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

    def test_parent_barrier_applies_across_layers(self, tmp_path: Path) -> None:
        """A higher-priority child negation cannot bypass an ignored parent."""
        (tmp_path / ".gitignore").write_text("!build/keep.txt\n")
        resolver = IgnoreResolver(tmp_path, default_patterns=["build/"])
        resolver.enter_directory("")

        assert resolver.is_dir_ignored("build") is True
        assert resolver.explain("build/keep.txt") == IgnoreDecision(
            ignored=True,
            source=PatternSource(file="<defaults>", line=None, pattern="build/"),
        )
        assert resolver.is_ignored("build/other.txt") is True

    def test_parent_reinclusion_applies_across_layers(self, tmp_path: Path) -> None:
        """Higher-priority rules can reopen a parent before including its child."""
        (tmp_path / ".gitignore").write_text("!build/\n!build/keep.txt\n")
        resolver = IgnoreResolver(tmp_path, default_patterns=["build/"])
        resolver.enter_directory("")

        assert resolver.is_dir_ignored("build") is False
        assert resolver.explain("build/keep.txt") == IgnoreDecision(
            ignored=False,
            source=PatternSource(file=".gitignore", line=2, pattern="!build/keep.txt"),
        )

    def test_custom_rules_respect_parent_barrier_and_file_order(self, tmp_path: Path) -> None:
        """Custom files retain declared order while enforcing reachable parents."""
        (tmp_path / ".first").write_text("cache/\n")
        (tmp_path / ".second").write_text("!cache/\ncache/*\n!cache/keep.txt\n")

        reopened = IgnoreResolver(
            tmp_path,
            custom_ignore_filenames=[".first", ".second"],
        )
        assert reopened.is_dir_ignored("cache") is False
        assert reopened.explain("cache/keep.txt") == IgnoreDecision(
            ignored=False,
            source=PatternSource(file=".second", line=3, pattern="!cache/keep.txt"),
        )
        assert reopened.is_ignored("cache/other.txt") is True

        closed = IgnoreResolver(
            tmp_path,
            custom_ignore_filenames=[".second", ".first"],
        )
        assert closed.explain("cache/keep.txt") == IgnoreDecision(
            ignored=True,
            source=PatternSource(file=".first", line=1, pattern="cache/"),
        )


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
        for path in ["debug.log", "important.log", "main.py", "module.pyc"]:
            assert resolver.explain(path).ignored == resolver.is_ignored(path)
        assert resolver.explain_dir("build").ignored == resolver.is_dir_ignored("build")


# ---------------------------------------------------------------------------
# load_all() — bulk discovery
# ---------------------------------------------------------------------------


class TestLoadAll:
    """Tests for load_all() bulk gitignore discovery."""

    def test_loads_all_gitignores(self, tmp_path: Path) -> None:
        """load_all() discovers nested .gitignore files without manual enter_directory."""
        (tmp_path / "src" / "lib").mkdir(parents=True)
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "src" / ".gitignore").write_text("*.bak\n")
        (tmp_path / "src" / "lib" / ".gitignore").write_text("*.dump\n")

        resolver = IgnoreResolver(tmp_path)
        resolver.load_all()

        assert resolver.is_ignored("app.log") is True
        assert resolver.is_ignored("src/file.bak") is True
        assert resolver.is_ignored("src/lib/core.dump") is True
        assert resolver.is_ignored("src/main.py") is False

    def test_prunes_ignored_directories(self, tmp_path: Path) -> None:
        """load_all() doesn't descend into ignored directories."""
        (tmp_path / "build" / "sub").mkdir(parents=True)
        (tmp_path / ".gitignore").write_text("build/\n")
        (tmp_path / "build" / ".gitignore").write_text("*.o\n")

        resolver = IgnoreResolver(tmp_path)
        resolver.load_all()

        # build/ is visited and pruned — its .gitignore is never loaded.
        assert resolver.is_dir_ignored("build") is True
        assert "build" in resolver._entered_dirs
        assert "build" in resolver._pruned_dirs

    def test_ignored_directory_gitignore_is_never_read(self, tmp_path: Path) -> None:
        """Manual discovery records ignored descendants without reading their rules."""
        (tmp_path / "build" / "deep").mkdir(parents=True)
        (tmp_path / ".gitignore").write_text("build/\n")
        (tmp_path / "build" / ".gitignore").write_text("!keep.txt\n")

        with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
            resolver = IgnoreResolver(tmp_path)
            resolver.enter_directory("build/deep")

        loaded_paths = [call.args[0] for call in reader.call_args_list]
        assert tmp_path / ".gitignore" in loaded_paths
        assert tmp_path / "build" / ".gitignore" not in loaded_paths
        assert resolver._entered_dirs == {"", "build", "build/deep"}
        assert resolver._pruned_dirs == {"build", "build/deep"}

    def test_defaults_and_custom_with_load_all(self, tmp_path: Path) -> None:
        """Defaults and custom files work alongside load_all()."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / ".myignore").write_text("*.draft\n")

        resolver = IgnoreResolver(
            tmp_path,
            default_patterns=["*.pyc"],
            custom_ignore_filenames=[".myignore"],
        )
        resolver.load_all()

        assert resolver.is_ignored("module.pyc") is True
        assert resolver.is_ignored("notes.draft") is True
        assert resolver.is_ignored("app.log") is True
        assert resolver.is_ignored("main.py") is False

    def test_load_all_idempotent(self, tmp_path: Path) -> None:
        """Calling load_all() twice doesn't duplicate layers."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        resolver = IgnoreResolver(tmp_path)
        resolver.load_all()
        initial_layers = len(resolver._gitignore_layers)
        resolver.load_all()
        assert len(resolver._gitignore_layers) == initial_layers

    def test_load_all_no_gitignore(self, tmp_path: Path) -> None:
        """load_all() works fine when no .gitignore files exist."""
        (tmp_path / "src").mkdir()
        resolver = IgnoreResolver(tmp_path)
        resolver.load_all()
        assert resolver.is_ignored("src/main.py") is False

    def test_load_all_explain_works(self, tmp_path: Path) -> None:
        """explain() works correctly after load_all()."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / ".gitignore").write_text("*.tmp\n")

        resolver = IgnoreResolver(tmp_path)
        resolver.load_all()

        decision = resolver.explain("src/debug.tmp")
        assert decision.ignored is True
        assert decision.source == PatternSource(file="src/.gitignore", line=1, pattern="*.tmp")


# ---------------------------------------------------------------------------
# auto_enter — on-demand .gitignore loading
# ---------------------------------------------------------------------------


class TestAutoEnter:
    """Tests for auto_enter=True on-demand .gitignore loading."""

    def test_is_ignored_auto_enter_loads_ancestors(self, tmp_path: Path) -> None:
        """auto_enter loads .gitignore files along the path."""
        (tmp_path / "src" / "lib").mkdir(parents=True)
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "src" / ".gitignore").write_text("*.bak\n")

        resolver = IgnoreResolver(tmp_path)
        # No enter_directory calls needed.
        assert resolver.is_ignored("src/lib/app.log", auto_enter=True) is True
        assert resolver.is_ignored("src/file.bak", auto_enter=True) is True
        assert resolver.is_ignored("src/main.py", auto_enter=True) is False

    def test_auto_enter_caches_entered_dirs(self, tmp_path: Path) -> None:
        """Repeated auto_enter calls for the same prefix don't re-enter directories."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / ".gitignore").write_text("*.tmp\n")
        resolver = IgnoreResolver(tmp_path)

        resolver.is_ignored("src/a.tmp", auto_enter=True)
        entered_after_first = len(resolver._entered_dirs)

        resolver.is_ignored("src/b.tmp", auto_enter=True)
        assert len(resolver._entered_dirs) == entered_after_first

    def test_auto_enter_with_defaults(self, tmp_path: Path) -> None:
        """Defaults layer works with auto_enter."""
        resolver = IgnoreResolver(tmp_path, default_patterns=["*.pyc"])
        assert resolver.is_ignored("module.pyc", auto_enter=True) is True
        assert resolver.is_ignored("main.py", auto_enter=True) is False

    def test_auto_enter_with_custom_files(self, tmp_path: Path) -> None:
        """Custom ignore files work with auto_enter."""
        (tmp_path / ".myignore").write_text("*.draft\n")
        resolver = IgnoreResolver(tmp_path, custom_ignore_filenames=[".myignore"])
        assert resolver.is_ignored("notes.draft", auto_enter=True) is True

    def test_is_dir_ignored_auto_enter(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("build/\n")
        resolver = IgnoreResolver(tmp_path)
        assert resolver.is_dir_ignored("build", auto_enter=True) is True
        assert resolver.is_dir_ignored("src", auto_enter=True) is False

    def test_explain_auto_enter(self, tmp_path: Path) -> None:
        """explain with auto_enter loads ancestors then returns full decision."""
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / ".gitignore").write_text("*.tmp\n")

        resolver = IgnoreResolver(tmp_path)
        decision = resolver.explain("src/debug.tmp", auto_enter=True)
        assert decision.ignored is True
        assert decision.source == PatternSource(file="src/.gitignore", line=1, pattern="*.tmp")

    def test_explain_dir_auto_enter(self, tmp_path: Path) -> None:
        (tmp_path / ".gitignore").write_text("build/\n")
        resolver = IgnoreResolver(tmp_path)
        decision = resolver.explain_dir("build", auto_enter=True)
        assert decision.ignored is True
        assert decision.source == PatternSource(file=".gitignore", line=1, pattern="build/")

    def test_auto_enter_root_file(self, tmp_path: Path) -> None:
        """auto_enter on a root-level file works (no parent directories to enter)."""
        (tmp_path / ".gitignore").write_text("*.log\n")
        resolver = IgnoreResolver(tmp_path)
        assert resolver.is_ignored("debug.log", auto_enter=True) is True
        assert resolver.is_ignored("main.py", auto_enter=True) is False

    def test_auto_enter_consistent_with_enter_directory(self, tmp_path: Path) -> None:
        """auto_enter and manual enter_directory produce the same results."""
        (tmp_path / "src" / "lib").mkdir(parents=True)
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "src" / ".gitignore").write_text("*.bak\n!keep.bak\n")

        paths = ["src/lib/app.log", "src/file.bak", "src/keep.bak", "src/main.py"]

        # auto_enter resolver.
        auto = IgnoreResolver(tmp_path)
        auto_results = [auto.is_ignored(p, auto_enter=True) for p in paths]

        # Manual resolver.
        manual = IgnoreResolver(tmp_path)
        manual.enter_directory("")
        manual.enter_directory("src")
        manual.enter_directory("src/lib")
        manual_results = [manual.is_ignored(p) for p in paths]

        assert auto_results == manual_results

    def test_manual_entry_order_does_not_change_precedence(self, tmp_path: Path) -> None:
        """All manual discovery orders resolve scopes root-to-deepest."""
        (tmp_path / "src" / "lib").mkdir(parents=True)
        (tmp_path / ".gitignore").write_text("*.log\n")
        (tmp_path / "src" / ".gitignore").write_text("!keep.log\n")
        (tmp_path / "src" / "lib" / ".gitignore").write_text("keep.log\n")

        expected = (
            IgnoreDecision(
                ignored=False,
                source=PatternSource(file="src/.gitignore", line=1, pattern="!keep.log"),
            ),
            IgnoreDecision(
                ignored=True,
                source=PatternSource(file="src/lib/.gitignore", line=1, pattern="keep.log"),
            ),
            IgnoreDecision(
                ignored=True,
                source=PatternSource(file=".gitignore", line=1, pattern="*.log"),
            ),
        )

        for order in permutations(("", "src", "src/lib")):
            resolver = IgnoreResolver(tmp_path)
            for directory in order:
                resolver.enter_directory(directory)
            assert (
                resolver.explain("src/keep.log"),
                resolver.explain("src/lib/keep.log"),
                resolver.explain("src/lib/other.log"),
            ) == expected
