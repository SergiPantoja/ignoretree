"""Tests for Git repository metadata discovery."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from conftest import GIT_AVAILABLE, git_check_ignore
from ignoretree import IgnoreDecision, IgnoreResolver, PatternSource
from ignoretree.git import locate_git_exclude


def _write_exclude(common_dir: Path, pattern: str = "*.secret\n") -> Path:
    exclude = common_dir / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    exclude.write_text(pattern)
    return exclude


def _assert_exclude_loaded(root: Path) -> None:
    assert IgnoreResolver(root).explain("value.secret") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file=".git/info/exclude", line=1, pattern="*.secret"),
    )


def test_normal_git_directory_exclude(tmp_path: Path) -> None:
    _write_exclude(tmp_path / ".git")

    _assert_exclude_loaded(tmp_path)


def test_relative_gitdir_target_without_commondir(tmp_path: Path) -> None:
    root = tmp_path / "component"
    git_dir = tmp_path / "super" / ".git" / "modules" / "component"
    root.mkdir()
    git_dir.mkdir(parents=True)
    (root / ".git").write_text("gitdir: ../super/.git/modules/component\n")
    _write_exclude(git_dir)

    _assert_exclude_loaded(root)


def test_absolute_gitdir_target_without_commondir(tmp_path: Path) -> None:
    root = tmp_path / "component"
    git_dir = tmp_path / "metadata"
    root.mkdir()
    git_dir.mkdir()
    (root / ".git").write_text(f"gitdir: {git_dir}\n")
    _write_exclude(git_dir)

    _assert_exclude_loaded(root)


def test_relative_commondir_target(tmp_path: Path) -> None:
    root = tmp_path / "linked"
    git_dir = tmp_path / "main.git" / "worktrees" / "linked"
    common_dir = tmp_path / "main.git"
    root.mkdir()
    git_dir.mkdir(parents=True)
    (root / ".git").write_text(f"gitdir: {git_dir}\n")
    (git_dir / "commondir").write_text("../..\n")
    _write_exclude(common_dir)

    _assert_exclude_loaded(root)


@pytest.mark.parametrize(
    "content",
    [
        "",
        "gitdir:\n",
        "gitdir: \n",
        "gitdir: bad\0path\n",
        "not-gitdir: metadata\n",
        "gitdir: metadata\nextra\n",
    ],
)
def test_malformed_git_file_fails_open(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    content: str,
) -> None:
    (tmp_path / ".git").write_text(content)

    with caplog.at_level(logging.DEBUG, logger="ignoretree.git"):
        decision = IgnoreResolver(tmp_path).explain("value.secret")

    assert decision == IgnoreDecision(ignored=False, source=None)
    assert "Git metadata" in caplog.text


def test_missing_gitdir_target_fails_open(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    (tmp_path / ".git").write_text("gitdir: missing\n")

    with caplog.at_level(logging.DEBUG, logger="ignoretree.git"):
        decision = IgnoreResolver(tmp_path).explain("value.secret")

    assert decision == IgnoreDecision(ignored=False, source=None)
    assert "Git directory" in caplog.text


def test_gitdir_target_must_be_a_directory(tmp_path: Path) -> None:
    target = tmp_path / "metadata"
    target.write_text("")
    (tmp_path / ".git").write_text(f"gitdir: {target}\n")

    assert locate_git_exclude(tmp_path) is None


def test_malformed_commondir_fails_open(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = tmp_path / "linked"
    git_dir = tmp_path / "metadata"
    root.mkdir()
    git_dir.mkdir()
    (root / ".git").write_text(f"gitdir: {git_dir}\n")
    (git_dir / "commondir").write_text("../common\nextra\n")
    _write_exclude(git_dir)

    with caplog.at_level(logging.DEBUG, logger="ignoretree.git"):
        decision = IgnoreResolver(root).explain("value.secret")

    assert decision == IgnoreDecision(ignored=False, source=None)
    assert "commondir" in caplog.text


def test_commondir_metadata_must_be_a_regular_file(tmp_path: Path) -> None:
    root = tmp_path / "linked"
    git_dir = tmp_path / "metadata"
    root.mkdir()
    (git_dir / "commondir").mkdir(parents=True)
    (root / ".git").write_text(f"gitdir: {git_dir}\n")

    assert locate_git_exclude(root) is None


def test_commondir_target_must_be_a_directory(tmp_path: Path) -> None:
    root = tmp_path / "linked"
    git_dir = tmp_path / "metadata"
    common_file = tmp_path / "common"
    root.mkdir()
    git_dir.mkdir()
    common_file.write_text("")
    (root / ".git").write_text(f"gitdir: {git_dir}\n")
    (git_dir / "commondir").write_text(str(common_file))

    assert locate_git_exclude(root) is None


@pytest.mark.parametrize("metadata_name", [".git", "commondir"])
def test_unreadable_metadata_file_fails_open(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    metadata_name: str,
) -> None:
    root = tmp_path / "linked"
    git_dir = tmp_path / "metadata"
    root.mkdir()
    git_dir.mkdir()
    git_file = root / ".git"
    commondir_file = git_dir / "commondir"
    git_file.write_text(f"gitdir: {git_dir}\n")
    commondir_file.write_text(".\n")
    _write_exclude(git_dir)
    unreadable = git_file if metadata_name == ".git" else commondir_file
    original_read_text = Path.read_text

    def guarded_read_text(path: Path, *args: object, **kwargs: object) -> str:
        if path == unreadable:
            raise PermissionError("unreadable metadata")
        return original_read_text(path, *args, **kwargs)

    with (
        patch.object(Path, "read_text", guarded_read_text),
        caplog.at_level(logging.DEBUG, logger="ignoretree.git"),
    ):
        decision = IgnoreResolver(root).explain("value.secret")

    assert decision == IgnoreDecision(ignored=False, source=None)
    assert "Could not read Git metadata" in caplog.text


def test_symlinked_external_exclude_is_not_read(tmp_path: Path) -> None:
    root = tmp_path / "linked"
    git_dir = tmp_path / "metadata"
    outside = tmp_path / "outside-exclude"
    root.mkdir()
    git_dir.mkdir()
    (root / ".git").write_text(f"gitdir: {git_dir}\n")
    outside.write_text("*.secret\n")
    (git_dir / "info").mkdir()
    try:
        (git_dir / "info" / "exclude").symlink_to(outside)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    assert IgnoreResolver(root).explain("value.secret") == IgnoreDecision(
        ignored=False,
        source=None,
    )


def test_git_marker_symlink_is_not_followed(tmp_path: Path) -> None:
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    try:
        (tmp_path / ".git").symlink_to(metadata, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"symlinks unavailable: {error}")

    assert locate_git_exclude(tmp_path) is None


def test_git_info_must_be_a_directory(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "info").write_text("")

    assert locate_git_exclude(tmp_path) is None


def test_missing_exclude_file_fails_open(tmp_path: Path) -> None:
    (tmp_path / ".git" / "info").mkdir(parents=True)

    assert locate_git_exclude(tmp_path) == tmp_path / ".git" / "info" / "exclude"
    assert IgnoreResolver(tmp_path).explain("value.secret") == IgnoreDecision(
        ignored=False,
        source=None,
    )


@pytest.mark.parametrize("location", ["git", "commondir", "info", "exclude"])
def test_metadata_inspection_errors_fail_open(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    location: str,
) -> None:
    root = tmp_path / "root"
    git_dir = tmp_path / "metadata"
    root.mkdir()
    git_dir.mkdir()
    git_marker = root / ".git"
    commondir = git_dir / "commondir"

    if location == "git":
        target = git_marker
    elif location == "commondir":
        git_marker.write_text(f"gitdir: {git_dir}\n")
        target = commondir
    else:
        git_marker.mkdir()
        info = git_marker / "info"
        if location == "info":
            target = info
        else:
            info.mkdir()
            target = info / "exclude"

    original_lstat = Path.lstat

    def guarded_lstat(path: Path) -> os.stat_result:
        if path == target:
            raise PermissionError("unreadable metadata")
        return original_lstat(path)

    with (
        patch.object(Path, "lstat", guarded_lstat),
        caplog.at_level(logging.DEBUG, logger="ignoretree.git"),
    ):
        assert locate_git_exclude(root) is None

    assert "Could not inspect Git metadata" in caplog.text


@pytest.mark.skipif(not GIT_AVAILABLE, reason="git not installed")
def test_real_linked_worktree_uses_common_exclude(tmp_path: Path) -> None:
    main = tmp_path / "main"
    linked = tmp_path / "linked"
    subprocess.run(["git", "init", str(main)], check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "--allow-empty", "-m", "Initial commit"],
        cwd=main,
        check=True,
        capture_output=True,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
        },
    )
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(linked)],
        cwd=main,
        check=True,
        capture_output=True,
    )
    exclude = _write_exclude(main / ".git")

    git_result = git_check_ignore(linked, "value.secret")
    decision = IgnoreResolver(linked).explain("value.secret")

    assert git_result.ignored is True
    assert git_result.source is not None
    git_source_path = Path(git_result.source.file)
    if not git_source_path.is_absolute():
        git_source_path = linked / git_source_path
    assert git_source_path.resolve() == exclude.resolve()
    assert (git_result.source.line, git_result.source.pattern) == (1, "*.secret")
    assert decision == IgnoreDecision(
        ignored=True,
        source=PatternSource(file=".git/info/exclude", line=1, pattern="*.secret"),
    )
