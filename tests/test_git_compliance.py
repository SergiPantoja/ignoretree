"""Differential tests comparing ignoretree directly with Git."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

import pytest

from conftest import GIT_AVAILABLE, GitIgnoreResult, GitPatternSource, git_check_ignore
from ignoretree import IgnoreDecision, IgnoreResolver, PatternSource

if os.environ.get("CI") and not GIT_AVAILABLE:
    raise RuntimeError("Git is required to run the differential test suite in CI")

pytestmark = pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")

ResolverMode = Literal["manual", "auto_enter", "load_all"]
RESOLVER_MODES: tuple[ResolverMode, ...] = ("manual", "auto_enter", "load_all")


@dataclass(frozen=True, slots=True)
class PathCase:
    """A path to compare, with its filesystem kind when relevant."""

    path: str
    is_dir: bool = False
    compare_pattern: bool = True


def _enter_ancestors(resolver: IgnoreResolver, path: str) -> None:
    """Load the same ancestor scopes that ``auto_enter`` loads for a path."""
    resolver.enter_directory("")
    parts = PurePosixPath(path.rstrip("/")).parts
    for depth in range(1, len(parts)):
        resolver.enter_directory("/".join(parts[:depth]))


def _resolve(repo: Path, case: PathCase, mode: ResolverMode) -> IgnoreDecision:
    """Resolve a path through one fresh ignoretree usage mode."""
    resolver = IgnoreResolver(repo)
    clean_path = case.path.rstrip("/")

    if mode == "manual":
        _enter_ancestors(resolver, case.path)
    elif mode == "load_all":
        resolver.load_all()

    auto_enter = mode == "auto_enter"
    if case.is_dir:
        return resolver.explain_dir(clean_path, auto_enter=auto_enter)
    return resolver.explain(clean_path, auto_enter=auto_enter)


def _source_tuple(
    source: GitPatternSource | PatternSource | None,
    *,
    compare_pattern: bool,
) -> tuple[str, int | None, str] | None:
    """Normalize Git and ignoretree provenance for direct comparison."""
    if source is None:
        return None
    pattern = source.pattern if compare_pattern else "<normalized by Git>"
    return source.file, source.line, pattern


def assert_matches_git(repo: Path, cases: Iterable[PathCase]) -> None:
    """Assert every ignoretree usage mode agrees with Git for each path."""
    for case in cases:
        git_result = git_check_ignore(repo, case.path)
        resolver_results = {mode: _resolve(repo, case, mode) for mode in RESOLVER_MODES}

        assert {mode: result.ignored for mode, result in resolver_results.items()} == {
            mode: git_result.ignored for mode in RESOLVER_MODES
        }, f"decision mismatch for {case.path!r}: Git returned {git_result!r}"
        assert {
            mode: _source_tuple(result.source, compare_pattern=case.compare_pattern)
            for mode, result in resolver_results.items()
        } == {
            mode: _source_tuple(git_result.source, compare_pattern=case.compare_pattern)
            for mode in RESOLVER_MODES
        }, f"provenance mismatch for {case.path!r}: Git returned {git_result!r}"


@pytest.mark.parametrize(
    ("patterns", "cases"),
    [
        pytest.param(
            "*.csv\n",
            [PathCase("data.csv"), PathCase("sub/data.csv"), PathCase("main.py")],
            id="unanchored-wildcard",
        ),
        pytest.param(
            "/root.log\n*.tmp\n",
            [PathCase("root.log"), PathCase("sub/root.log"), PathCase("sub/cache.tmp")],
            id="anchored-and-unanchored",
        ),
        pytest.param(
            "docs/*.txt\n",
            [PathCase("docs/readme.txt"), PathCase("src/docs/readme.txt")],
            id="slash-containing",
        ),
        pytest.param(
            "file?.txt\nreport[0-9].csv\n",
            [
                PathCase("file1.txt"),
                PathCase("file10.txt"),
                PathCase("report7.csv"),
                PathCase("reportx.csv"),
            ],
            id="question-mark-and-range",
        ),
        pytest.param(
            "cache/**\n**/generated.log\n",
            [
                PathCase("cache/item.bin"),
                PathCase("cache/deep/item.bin"),
                PathCase("src/generated.log"),
                PathCase("generated.log"),
            ],
            id="double-star",
        ),
        pytest.param(
            "build_output/\n__pycache__/\n",
            [
                PathCase("build_output/artifact"),
                PathCase("src/__pycache__/module.pyc"),
                PathCase("src/main.py"),
            ],
            id="directory-patterns",
        ),
        pytest.param(
            "*.log\n!important.log\n",
            [PathCase("debug.log"), PathCase("important.log"), PathCase("main.py")],
            id="negation",
        ),
        pytest.param(
            "*/backup/*\n!*/backup/backup.sh\n",
            [
                PathCase("project/backup/data.zip"),
                PathCase("project/backup/backup.sh"),
                PathCase("other/backup/old.tar"),
            ],
            id="wildcard-directory-negation",
        ),
        pytest.param(
            "folder/*\n!folder/keep.txt\n",
            [
                PathCase("folder/file.txt"),
                PathCase("folder/keep.txt"),
                PathCase("folder/sub/deep.txt"),
            ],
            id="wildcard-contents",
        ),
        pytest.param(
            "*.log   \nname\\ \n",
            [
                # Git strips the unescaped suffix in verbose output, while
                # PatternSource intentionally retains the raw source text.
                PathCase("debug.log", compare_pattern=False),
                PathCase("name "),
                PathCase("name"),
            ],
            id="trailing-spaces",
        ),
        pytest.param(
            "# comment\n\n\\#literal\n\\!important\n",
            [
                PathCase("#literal"),
                PathCase("!important"),
                PathCase("comment"),
            ],
            id="comments-blanks-and-escaped-specials",
        ),
        pytest.param(
            "café.txt\n日本語.log\n",
            [PathCase("café.txt"), PathCase("日本語.log"), PathCase("CAFÉ.txt")],
            id="case-sensitive-unicode",
        ),
        pytest.param(
            "dir with space/*.log\nfile\tname.log\n",
            [
                PathCase("dir with space/a file.log"),
                PathCase("dir/a file.log"),
                PathCase("file\tname.log"),
            ],
            id="nul-delimited-provenance",
        ),
    ],
)
def test_root_gitignore_matches_git(
    git_repo: Path,
    patterns: str,
    cases: list[PathCase],
) -> None:
    """Root patterns produce the same decision and provenance in every mode."""
    (git_repo / ".gitignore").write_text(patterns)
    assert_matches_git(git_repo, cases)


def test_nested_gitignores_match_git(git_repo: Path) -> None:
    """Nested rules retain Git's scope and root-to-deepest precedence."""
    (git_repo / "src" / "lib").mkdir(parents=True)
    (git_repo / ".gitignore").write_text("*.log\n")
    (git_repo / "src" / ".gitignore").write_text("*.bak\n!audit.log\n")
    (git_repo / "src" / "lib" / ".gitignore").write_text("*.dump\n")

    assert_matches_git(
        git_repo,
        [
            PathCase("app.log"),
            PathCase("src/audit.log"),
            PathCase("src/debug.log"),
            PathCase("src/file.bak"),
            PathCase("file.bak"),
            PathCase("src/lib/core.dump"),
            PathCase("src/core.dump"),
        ],
    )


def test_git_oracle_distinguishes_negation_from_ignored(git_repo: Path) -> None:
    """Quiet and verbose Git results are combined without conflating negation."""
    (git_repo / ".gitignore").write_text("*.log\n!important.log\n")

    assert git_check_ignore(git_repo, "debug.log") == GitIgnoreResult(
        ignored=True,
        source=GitPatternSource(file=".gitignore", line=1, pattern="*.log"),
    )
    assert git_check_ignore(git_repo, "important.log") == GitIgnoreResult(
        ignored=False,
        source=GitPatternSource(file=".gitignore", line=2, pattern="!important.log"),
    )
    assert git_check_ignore(git_repo, "main.py") == GitIgnoreResult(
        ignored=False,
        source=None,
    )


def test_git_oracle_rejects_git_errors(tmp_path: Path) -> None:
    """Git failures are errors, never ordinary nonmatches."""
    with pytest.raises(subprocess.CalledProcessError) as error:
        git_check_ignore(tmp_path, "main.py")

    assert error.value.returncode not in (0, 1)


@pytest.mark.xfail(strict=True, reason="H1: ignored-parent handling is fixed in Priority 1")
def test_ignored_parent_negation_matches_git(git_repo: Path) -> None:
    """A file cannot be re-included while its parent remains ignored."""
    (git_repo / ".gitignore").write_text("build/\n!build/keep.txt\n")

    assert_matches_git(
        git_repo,
        [PathCase("build/keep.txt"), PathCase("build/output.o")],
    )


@pytest.mark.xfail(strict=True, reason="H1: directory negation is fixed in Priority 1")
def test_directory_negation_matches_git(git_repo: Path) -> None:
    """Directory-only negation must make traversal directories reachable."""
    (git_repo / "data" / "raw").mkdir(parents=True)
    (git_repo / "data" / "processed").mkdir(parents=True)
    (git_repo / ".gitignore").write_text("data/**\n!data/**/\n!.gitkeep\n!data/raw/*\n")

    assert_matches_git(
        git_repo,
        [
            PathCase("data/raw/", is_dir=True),
            PathCase("data/processed/", is_dir=True),
            PathCase("data/raw/.gitkeep"),
            PathCase("data/raw/raw_file.csv"),
            PathCase("data/processed/processed_file.csv"),
        ],
    )


@pytest.mark.xfail(strict=True, reason="H1: ignored-parent loading is fixed in Priority 1")
def test_nested_gitignore_below_ignored_parent_matches_git(git_repo: Path) -> None:
    """No mode may apply a nested ignore file below an ignored parent."""
    (git_repo / "build").mkdir()
    (git_repo / ".gitignore").write_text("build/\n")
    (git_repo / "build" / ".gitignore").write_text("!keep.txt\n")

    assert_matches_git(git_repo, [PathCase("build/keep.txt")])
