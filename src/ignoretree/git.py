"""Internal discovery of Git repository metadata paths."""

from __future__ import annotations

import logging
import stat
from pathlib import Path

logger = logging.getLogger(__name__)


def locate_git_common_dir(root: Path) -> Path | None:
    """Return the effective Git common directory without invoking Git."""
    git_marker = root / ".git"
    try:
        marker_mode = git_marker.lstat().st_mode
    except FileNotFoundError:
        return None
    except OSError as error:
        logger.debug("Could not inspect Git metadata %s: %s", git_marker, error)
        return None

    if stat.S_ISDIR(marker_mode):
        return git_marker
    if not stat.S_ISREG(marker_mode):
        logger.debug("Git metadata is not a regular file or directory: %s", git_marker)
        return None

    gitdir_text = _read_metadata_file(git_marker)
    if gitdir_text is None:
        return None
    gitdir_target = _parse_metadata_path(
        gitdir_text,
        path=git_marker,
        prefix="gitdir: ",
    )
    if gitdir_target is None:
        return None

    git_dir = _resolve_directory(git_marker.parent, gitdir_target, label="Git directory")
    if git_dir is None:
        return None

    commondir_file = git_dir / "commondir"
    try:
        commondir_mode = commondir_file.lstat().st_mode
    except FileNotFoundError:
        return git_dir
    except OSError as error:
        logger.debug("Could not inspect Git metadata %s: %s", commondir_file, error)
        return None

    if not stat.S_ISREG(commondir_mode):
        logger.debug("Git commondir metadata is not a regular file: %s", commondir_file)
        return None

    commondir_text = _read_metadata_file(commondir_file)
    if commondir_text is None:
        return None
    commondir_target = _parse_metadata_path(commondir_text, path=commondir_file)
    if commondir_target is None:
        return None

    return _resolve_directory(git_dir, commondir_target, label="Git common directory")


def locate_git_exclude(root: Path) -> Path | None:
    """Return a safe effective ``info/exclude`` path when metadata is available."""
    common_dir = locate_git_common_dir(root)
    if common_dir is None:
        return None

    info_dir = common_dir / "info"
    exclude = info_dir / "exclude"
    try:
        info_mode = info_dir.lstat().st_mode
    except FileNotFoundError:
        return exclude
    except OSError as error:
        logger.debug("Could not inspect Git metadata %s: %s", info_dir, error)
        return None

    if not stat.S_ISDIR(info_mode):
        logger.debug("Git info metadata is not a directory: %s", info_dir)
        return None

    try:
        exclude_mode = exclude.lstat().st_mode
    except FileNotFoundError:
        return exclude
    except OSError as error:
        logger.debug("Could not inspect Git metadata %s: %s", exclude, error)
        return None

    if stat.S_ISLNK(exclude_mode):
        logger.debug("Git exclude metadata is a symlink: %s", exclude)
        return None
    return exclude


def _read_metadata_file(path: Path) -> str | None:
    """Read one UTF-8 Git metadata control file with fail-open behavior."""
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        logger.debug("Could not read Git metadata %s: %s", path, error)
        return None


def _parse_metadata_path(
    text: str,
    *,
    path: Path,
    prefix: str = "",
) -> str | None:
    """Parse exactly one nonempty path from a Git control file."""
    lines = text.splitlines()
    if len(lines) != 1 or not lines[0].startswith(prefix):
        logger.debug("Malformed Git metadata path in %s", path)
        return None

    target = lines[0][len(prefix) :]
    if not target or "\0" in target:
        logger.debug("Malformed Git metadata path in %s", path)
        return None
    return target


def _resolve_directory(base: Path, target: str, *, label: str) -> Path | None:
    """Resolve a relative or absolute metadata target to an existing directory."""
    candidate = Path(target)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve(strict=True)
        mode = resolved.lstat().st_mode
    except (OSError, RuntimeError) as error:
        logger.debug("%s is unavailable at %s: %s", label, candidate, error)
        return None
    if not stat.S_ISDIR(mode):
        logger.debug("%s is not a directory: %s", label, resolved)
        return None
    return resolved
