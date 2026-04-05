"""Git compliance tests — validate our expectations against real git.

Every test mirrors a scenario from the main test suite and verifies the
expected result with ``git check-ignore``.  If git disagrees with our
expectation, the test here fails and we update the main suite (or
document the deviation).

Only single-layer ``.gitignore`` scenarios can be validated this way
because ``git check-ignore`` uses the on-disk ``.gitignore`` files
directly.  Multi-layer behaviour (defaults, info/exclude, custom files,
cross-layer negation) is tested in the main suite only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import GIT_AVAILABLE, git_check_ignore

pytestmark = pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")


# ---------------------------------------------------------------------------
# Basic glob patterns
# ---------------------------------------------------------------------------


class TestBasicGlob:
    """Verify basic glob matching agrees with git."""

    def test_wildcard_extension(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("*.csv\n")
        assert git_check_ignore(git_repo, "data.csv") is True
        assert git_check_ignore(git_repo, "sub/data.csv") is True
        assert git_check_ignore(git_repo, "main.py") is False

    def test_pyc_and_pycache(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("*.pyc\n__pycache__/\n")
        assert git_check_ignore(git_repo, "module.pyc") is True
        assert git_check_ignore(git_repo, "__pycache__/something") is True
        assert git_check_ignore(git_repo, "src/main.py") is False

    def test_log_extension(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("*.log\n")
        assert git_check_ignore(git_repo, "debug.log") is True
        assert git_check_ignore(git_repo, "main.py") is False


# ---------------------------------------------------------------------------
# Directory patterns
# ---------------------------------------------------------------------------


class TestDirectoryPattern:
    """Verify trailing-slash directory patterns match git."""

    def test_dir_pattern_ignores_contents(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("build_output/\n")
        assert git_check_ignore(git_repo, "build_output/artifact") is True

    def test_dir_pattern_pycache(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("__pycache__/\n")
        assert git_check_ignore(git_repo, "__pycache__/module.cpython.pyc") is True
        assert git_check_ignore(git_repo, "src/__pycache__/module.cpython.pyc") is True


# ---------------------------------------------------------------------------
# Negation patterns
# ---------------------------------------------------------------------------


class TestNegation:
    """Verify negation pattern behaviour matches git."""

    def test_simple_negation(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("*.log\n!important.log\n")
        assert git_check_ignore(git_repo, "debug.log") is True
        assert git_check_ignore(git_repo, "important.log") is False

    def test_dir_exclusion_then_negation(self, git_repo: Path) -> None:
        """build/ + !build/keep.txt — git says parent exclusion is final."""
        (git_repo / ".gitignore").write_text("build/\n!build/keep.txt\n")
        assert git_check_ignore(git_repo, "build/keep.txt") is True
        assert git_check_ignore(git_repo, "build/output.o") is True

    def test_negation_with_wildcard_directory(self, git_repo: Path) -> None:
        """*/backup/* + negation of a specific file."""
        (git_repo / ".gitignore").write_text("*/backup/*\n!*/backup/backup.sh\n")
        assert git_check_ignore(git_repo, "project/backup/data.zip") is True
        assert git_check_ignore(git_repo, "project/backup/backup.sh") is False
        assert git_check_ignore(git_repo, "other/backup/old.tar") is True
        assert git_check_ignore(git_repo, "other/backup/backup.sh") is False


# ---------------------------------------------------------------------------
# Wildcard content patterns (folder/*)
# ---------------------------------------------------------------------------


class TestWildcardContents:
    """Verify folder/* vs folder/ semantics match git."""

    def test_folder_star_ignores_direct_children(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("folder/*\n")
        assert git_check_ignore(git_repo, "folder/file.txt") is True

    def test_folder_star_vs_deep_path(self, git_repo: Path) -> None:
        """folder/* matches nested paths in git (not just direct children)."""
        (git_repo / ".gitignore").write_text("folder/*\n")
        # git treats folder/* as matching all contents recursively.
        assert git_check_ignore(git_repo, "folder/sub/deep.txt") is True

    def test_folder_star_with_negation(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("folder/*\n!folder/keep.txt\n")
        assert git_check_ignore(git_repo, "folder/file.txt") is True
        assert git_check_ignore(git_repo, "folder/keep.txt") is False


# ---------------------------------------------------------------------------
# Complex data directory patterns
# ---------------------------------------------------------------------------


class TestDataDirectoryPattern:
    """Verify the data/** + negation pattern used for .gitkeep workflows."""

    def test_data_globstar_with_dir_negation(self, git_repo: Path) -> None:
        """data/** + !data/**/ + !.gitkeep + !data/raw/*"""
        (git_repo / ".gitignore").write_text("data/**\n!data/**/\n!.gitkeep\n!data/raw/*\n")
        # Need to create directories so git can resolve them
        (git_repo / "data" / "raw").mkdir(parents=True)
        (git_repo / "data" / "processed").mkdir(parents=True)

        # Directories un-ignored by !data/**/
        assert git_check_ignore(git_repo, "data/raw/") is False
        assert git_check_ignore(git_repo, "data/processed/") is False

        # .gitkeep un-ignored
        assert git_check_ignore(git_repo, "data/raw/.gitkeep") is False

        # raw/* un-ignored by !data/raw/*
        assert git_check_ignore(git_repo, "data/raw/raw_file.csv") is False

        # processed files stay ignored (no negation covers them)
        assert git_check_ignore(git_repo, "data/processed/processed_file.csv") is True


# ---------------------------------------------------------------------------
# Trailing whitespace / escaped spaces
# ---------------------------------------------------------------------------


class TestTrailingWhitespace:
    """Verify git's handling of trailing whitespace in patterns."""

    def test_unescaped_trailing_space_stripped(self, git_repo: Path) -> None:
        """Unescaped trailing whitespace is stripped from patterns."""
        (git_repo / ".gitignore").write_text("*.log   \n")
        assert git_check_ignore(git_repo, "debug.log") is True


# ---------------------------------------------------------------------------
# Comments and blank lines
# ---------------------------------------------------------------------------


class TestCommentsAndBlanks:
    """Verify comments and blank lines are properly skipped."""

    def test_comment_only_gitignore(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("# just a comment\n#main.py\n")
        assert git_check_ignore(git_repo, "main.py") is False

    def test_empty_gitignore(self, git_repo: Path) -> None:
        (git_repo / ".gitignore").write_text("")
        assert git_check_ignore(git_repo, "main.py") is False


# ---------------------------------------------------------------------------
# Nested .gitignore scoping
# ---------------------------------------------------------------------------


class TestNestedGitignore:
    """Verify nested .gitignore scoping matches git."""

    def test_nested_gitignore_only_affects_subtree(self, git_repo: Path) -> None:
        """A .gitignore in src/ only affects files under src/."""
        (git_repo / "src").mkdir()
        (git_repo / "src" / ".gitignore").write_text("*.tmp\n")
        assert git_check_ignore(git_repo, "src/debug.tmp") is True
        assert git_check_ignore(git_repo, "debug.tmp") is False

    def test_deeper_gitignore_negation_overrides_parent(self, git_repo: Path) -> None:
        """A .gitignore in src/ can negate patterns from root .gitignore."""
        (git_repo / "src").mkdir()
        (git_repo / ".gitignore").write_text("*.log\n")
        (git_repo / "src" / ".gitignore").write_text("!audit.log\n")
        assert git_check_ignore(git_repo, "debug.log") is True
        assert git_check_ignore(git_repo, "src/audit.log") is False
        assert git_check_ignore(git_repo, "src/debug.log") is True

    def test_deep_nesting_three_levels(self, git_repo: Path) -> None:
        """Three levels of .gitignore files accumulate correctly."""
        (git_repo / "src" / "lib").mkdir(parents=True)
        (git_repo / ".gitignore").write_text("*.log\n")
        (git_repo / "src" / ".gitignore").write_text("*.bak\n")
        (git_repo / "src" / "lib" / ".gitignore").write_text("*.dump\n")

        # Root .gitignore: *.log applies everywhere.
        assert git_check_ignore(git_repo, "app.log") is True
        assert git_check_ignore(git_repo, "src/app.log") is True
        assert git_check_ignore(git_repo, "src/lib/app.log") is True

        # src/.gitignore: *.bak applies under src/ only.
        assert git_check_ignore(git_repo, "src/file.bak") is True
        assert git_check_ignore(git_repo, "src/lib/file.bak") is True
        assert git_check_ignore(git_repo, "file.bak") is False

        # src/lib/.gitignore: *.dump applies under src/lib/ only.
        assert git_check_ignore(git_repo, "src/lib/core.dump") is True
        assert git_check_ignore(git_repo, "src/core.dump") is False
