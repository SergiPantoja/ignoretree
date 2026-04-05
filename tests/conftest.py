"""Shared fixtures for the ignoretree test suite."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

GIT_AVAILABLE = shutil.which("git") is not None


def git_check_ignore(repo_path: Path, file_path: str) -> bool:
    """Ask git whether *file_path* would be ignored.

    Returns ``True`` when ``git check-ignore`` exits 0 (ignored),
    ``False`` when it exits 1 (not ignored).
    """
    result = subprocess.run(
        ["git", "check-ignore", "-q", file_path],
        cwd=repo_path,
        capture_output=True,
    )
    return result.returncode == 0


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
    return tmp_path
