"""Shared fixtures for the ignoretree test suite."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

GIT_AVAILABLE = shutil.which("git") is not None


@dataclass(frozen=True, slots=True)
class GitPatternSource:
    """Pattern provenance reported by ``git check-ignore --verbose``."""

    file: str
    line: int
    pattern: str


@dataclass(frozen=True, slots=True)
class GitIgnoreResult:
    """Git's ignore decision and the pattern that produced it, if any."""

    ignored: bool
    source: GitPatternSource | None


def _run_git_check_ignore(
    repo_path: Path,
    *options: str,
    file_path: str,
) -> subprocess.CompletedProcess[bytes]:
    """Run ``git check-ignore`` with a NUL-terminated path on stdin."""
    result = subprocess.run(
        ["git", "check-ignore", *options, "-z", "--no-index", "--stdin"],
        cwd=repo_path,
        input=os.fsencode(file_path) + b"\0",
        capture_output=True,
    )
    if result.returncode not in (0, 1):
        raise subprocess.CalledProcessError(
            result.returncode,
            result.args,
            output=result.stdout,
            stderr=result.stderr,
        )
    return result


def git_check_ignore(repo_path: Path, file_path: str) -> GitIgnoreResult:
    """Ask Git whether *file_path* is ignored and obtain its provenance.

    Quiet mode distinguishes an ignored path from a negation. Verbose mode
    reports the last matching pattern for both outcomes, so it is run
    separately and parsed using Git's NUL-delimited output format.
    """
    quiet = _run_git_check_ignore(repo_path, "--quiet", file_path=file_path)
    verbose = _run_git_check_ignore(repo_path, "--verbose", file_path=file_path)

    source: GitPatternSource | None = None
    if verbose.returncode == 0:
        fields = verbose.stdout.removesuffix(b"\0").split(b"\0")
        if len(fields) != 4:
            raise ValueError(f"Unexpected git check-ignore output: {verbose.stdout!r}")
        source_file, line, pattern, reported_path = (os.fsdecode(field) for field in fields)
        if reported_path != file_path:
            raise ValueError(
                f"git check-ignore reported path {reported_path!r}, expected {file_path!r}"
            )
        source = GitPatternSource(file=source_file, line=int(line), pattern=pattern)

    return GitIgnoreResult(ignored=quiet.returncode == 0, source=source)


@pytest.fixture()
def git_repo(tmp_path: Path) -> Path:
    """Initialise a throwaway git repository for compliance tests."""
    subprocess.run(
        ["git", "init", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "core.ignorecase", "false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "core.precomposeunicode", "false"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    return tmp_path
