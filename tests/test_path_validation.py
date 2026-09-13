"""Path-contract and ignore-file containment tests."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from ignoretree import IgnoreDecision, IgnoreResolver, PatternSource
from ignoretree.reader import read_ignore_file


class GenericPathLike(os.PathLike[str]):
    """Non-Path ``os.PathLike`` used to verify the strict string contract."""

    def __fspath__(self) -> str:
        return "src/main.py"


INVALID_PATHS: tuple[object, ...] = (
    "",
    "/absolute/path",
    "//server/share",
    "C:/windows/path",
    "C:drive-relative",
    "../outside",
    "src/../outside",
    ".",
    "./src",
    "src/./main.py",
    "src//main.py",
    "src\\main.py",
    "src\0main.py",
    Path("src/main.py"),
    GenericPathLike(),
    b"src/main.py",
)

INVALID_DIRECTORY_PATHS: tuple[object, ...] = INVALID_PATHS[1:]


@pytest.mark.parametrize("method_name", ["is_ignored", "explain"])
@pytest.mark.parametrize("invalid_path", INVALID_PATHS)
def test_query_apis_reject_noncanonical_paths(
    tmp_path: Path,
    method_name: str,
    invalid_path: object,
) -> None:
    resolver = IgnoreResolver(tmp_path)
    method = getattr(resolver, method_name)
    expected_error = TypeError if not isinstance(invalid_path, str) else ValueError

    with (
        patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader,
        pytest.raises(expected_error),
    ):
        method(invalid_path, auto_enter=True)

    assert reader.call_count == 0
    assert resolver._entered_dirs == set()


@pytest.mark.parametrize("method_name", ["is_dir_ignored", "explain_dir"])
@pytest.mark.parametrize("invalid_path", ("", *INVALID_DIRECTORY_PATHS))
def test_directory_query_apis_reject_noncanonical_paths(
    tmp_path: Path,
    method_name: str,
    invalid_path: object,
) -> None:
    resolver = IgnoreResolver(tmp_path)
    method = getattr(resolver, method_name)
    expected_error = TypeError if not isinstance(invalid_path, str) else ValueError

    with (
        patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader,
        pytest.raises(expected_error),
    ):
        method(invalid_path, auto_enter=True)

    assert reader.call_count == 0
    assert resolver._entered_dirs == set()


@pytest.mark.parametrize("invalid_path", INVALID_DIRECTORY_PATHS)
def test_enter_directory_rejects_noncanonical_paths(
    tmp_path: Path,
    invalid_path: object,
) -> None:
    resolver = IgnoreResolver(tmp_path)
    expected_error = TypeError if not isinstance(invalid_path, str) else ValueError

    with (
        patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader,
        pytest.raises(expected_error),
    ):
        resolver.enter_directory(cast(Any, invalid_path))

    assert reader.call_count == 0
    assert resolver._entered_dirs == set()


def test_directory_apis_normalize_one_trailing_slash(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / ".gitignore").write_text("src/\n")
    resolver = IgnoreResolver(tmp_path)

    resolver.enter_directory("src/")

    assert resolver._entered_dirs == {"", "src"}
    assert resolver.is_dir_ignored("src/") is True
    assert resolver.explain_dir("src/") == resolver.explain_dir("src")


def test_file_query_apis_reject_trailing_slash(tmp_path: Path) -> None:
    resolver = IgnoreResolver(tmp_path)

    with pytest.raises(ValueError):
        resolver.is_ignored("src/")
    with pytest.raises(ValueError):
        resolver.explain("src/")


@pytest.mark.parametrize(
    "invalid_filename",
    (
        "",
        ".",
        "..",
        "../outside",
        "nested/ignore",
        "/absolute",
        "C:/windows",
        "name\\ignore",
        "name\0ignore",
        ".git",
        ".gitignore",
        Path(".custom"),
        GenericPathLike(),
    ),
)
def test_custom_ignore_filenames_must_be_safe_unique_basenames(
    tmp_path: Path,
    invalid_filename: object,
) -> None:
    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        expected_error = TypeError if not isinstance(invalid_filename, str) else ValueError
        with pytest.raises(expected_error):
            IgnoreResolver(
                tmp_path,
                custom_ignore_filenames=[cast(Any, invalid_filename)],
            )

    assert reader.call_count == 0


def test_duplicate_custom_ignore_filenames_are_rejected_before_reads(tmp_path: Path) -> None:
    with (
        patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader,
        pytest.raises(ValueError),
    ):
        IgnoreResolver(tmp_path, custom_ignore_filenames=[".custom", ".custom"])

    assert reader.call_count == 0


def test_invalid_query_never_reads_or_exposes_outside_ignore_file(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / ".gitignore").write_text("secret.txt\n")

    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        resolver = IgnoreResolver(root)
        baseline_reads = reader.call_count
        with pytest.raises(ValueError):
            resolver.explain("../outside/secret.txt", auto_enter=True)

    assert reader.call_count == baseline_reads
    assert resolver._entered_dirs == set()


def test_root_is_resolved_and_validated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    monkeypatch.chdir(tmp_path)

    resolver = IgnoreResolver(Path("repo"))

    assert resolver._root == root.resolve()
    assert resolver._root.is_absolute()


def test_missing_root_is_rejected(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        IgnoreResolver(tmp_path / "missing")


def test_file_root_is_rejected(tmp_path: Path) -> None:
    root_file = tmp_path / "file.txt"
    root_file.write_text("")

    with pytest.raises(NotADirectoryError):
        IgnoreResolver(root_file)


def _symlink_or_skip(link: Path, target: Path, *, target_is_directory: bool = False) -> None:
    """Create a symlink or skip where the platform forbids test symlinks."""
    try:
        link.symlink_to(target, target_is_directory=target_is_directory)
    except (NotImplementedError, OSError) as error:
        pytest.skip(f"symlinks unavailable: {error}")


def test_symlinked_ancestor_stops_discovery_but_keeps_lexical_matching(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (root / ".gitignore").write_text("*.log\n")
    (outside / ".gitignore").write_text("*.secret\n!visible.log\n")
    _symlink_or_skip(root / "linked", outside, target_is_directory=True)

    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        resolver = IgnoreResolver(root)
        log_decision = resolver.explain("linked/deep/visible.log", auto_enter=True)
        secret_decision = resolver.explain("linked/deep/value.secret", auto_enter=True)

    loaded_paths = [call.args[0] for call in reader.call_args_list]
    assert outside / ".gitignore" not in loaded_paths
    assert root / "linked" / ".gitignore" not in loaded_paths
    assert resolver._discovery_stopped_dirs == {"linked", "linked/deep"}
    assert log_decision == IgnoreDecision(
        ignored=True,
        source=PatternSource(file=".gitignore", line=1, pattern="*.log"),
    )
    assert secret_decision == IgnoreDecision(ignored=False, source=None)


def test_load_all_does_not_follow_symlinked_directories(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / ".gitignore").write_text("*.secret\n")
    _symlink_or_skip(root / "linked", outside, target_is_directory=True)

    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        resolver = IgnoreResolver(root)
        resolver.load_all()

    loaded_paths = [call.args[0] for call in reader.call_args_list]
    assert outside / ".gitignore" not in loaded_paths
    assert root / "linked" / ".gitignore" not in loaded_paths
    assert "linked" in resolver._discovery_stopped_dirs


def test_symlinked_gitignore_is_not_read(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    outside_ignore = outside / "rules"
    outside_ignore.write_text("*.secret\n")
    _symlink_or_skip(root / ".gitignore", outside_ignore)

    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        resolver = IgnoreResolver(root)
        decision = resolver.explain("value.secret", auto_enter=True)

    assert outside_ignore not in [call.args[0] for call in reader.call_args_list]
    assert decision == IgnoreDecision(ignored=False, source=None)


def test_symlinked_custom_ignore_file_is_not_read(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    outside_ignore = outside / "rules"
    outside_ignore.write_text("*.secret\n")
    _symlink_or_skip(root / ".custom", outside_ignore)

    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        resolver = IgnoreResolver(root, custom_ignore_filenames=[".custom"])
        decision = resolver.explain("value.secret")

    assert outside_ignore not in [call.args[0] for call in reader.call_args_list]
    assert decision == IgnoreDecision(ignored=False, source=None)


def test_symlinked_info_exclude_is_not_read(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    (root / ".git" / "info").mkdir(parents=True)
    outside.mkdir()
    outside_exclude = outside / "exclude"
    outside_exclude.write_text("*.secret\n")
    _symlink_or_skip(root / ".git" / "info" / "exclude", outside_exclude)

    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        resolver = IgnoreResolver(root)
        decision = resolver.explain("value.secret")

    assert outside_exclude not in [call.args[0] for call in reader.call_args_list]
    assert decision == IgnoreDecision(ignored=False, source=None)


def test_existing_and_nonexistent_query_resolve_lexically_the_same(tmp_path: Path) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / ".gitignore").write_text("src/*.log\n")
    resolver = IgnoreResolver(tmp_path)

    before = resolver.explain("src/app.log", auto_enter=True)
    (tmp_path / "src" / "app.log").write_text("")
    after = resolver.explain("src/app.log", auto_enter=True)

    assert (
        before
        == after
        == IgnoreDecision(
            ignored=True,
            source=PatternSource(file=".gitignore", line=1, pattern="src/*.log"),
        )
    )


def test_regular_file_ancestor_stops_discovery_but_keeps_lexical_matching(
    tmp_path: Path,
) -> None:
    (tmp_path / ".gitignore").write_text("*.log\n")
    (tmp_path / "node").write_text("")
    resolver = IgnoreResolver(tmp_path)

    decision = resolver.explain("node/child.log", auto_enter=True)

    assert "node" in resolver._discovery_stopped_dirs
    assert decision == IgnoreDecision(
        ignored=True,
        source=PatternSource(file=".gitignore", line=1, pattern="*.log"),
    )


def test_lstat_error_stops_discovery(tmp_path: Path) -> None:
    resolver = IgnoreResolver(tmp_path)
    target = tmp_path / "locked"
    original_lstat = Path.lstat

    def guarded_lstat(path: Path) -> os.stat_result:
        if path == target:
            raise PermissionError
        return original_lstat(path)

    with patch.object(Path, "lstat", guarded_lstat):
        resolver.enter_directory("locked")

    assert "locked" in resolver._discovery_stopped_dirs


def test_resolution_error_stops_discovery(tmp_path: Path) -> None:
    resolver = IgnoreResolver(tmp_path)
    resolver.enter_directory("")
    target = tmp_path / "unstable"
    original_resolve = Path.resolve

    def guarded_resolve(path: Path, strict: bool = False) -> Path:
        if path == target:
            raise RuntimeError("simulated symlink loop")
        return original_resolve(path, strict=strict)

    with patch.object(Path, "resolve", guarded_resolve):
        resolver.enter_directory("unstable")

    assert "unstable" in resolver._discovery_stopped_dirs


def test_post_check_escape_stops_discovery(tmp_path: Path) -> None:
    resolver = IgnoreResolver(tmp_path)
    resolver.enter_directory("")
    target = tmp_path / "changed"
    outside = tmp_path.parent / "outside"
    original_resolve = Path.resolve

    def escaped_resolve(path: Path, strict: bool = False) -> Path:
        if path == target:
            return outside
        return original_resolve(path, strict=strict)

    with patch.object(Path, "resolve", escaped_resolve):
        resolver.enter_directory("changed")

    assert "changed" in resolver._discovery_stopped_dirs
