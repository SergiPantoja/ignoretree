"""Internal file reader for gitignore-format files."""

from __future__ import annotations

import logging
from pathlib import Path

from ignoretree.models import PatternSource

logger = logging.getLogger(__name__)


def read_ignore_file(
    path: Path,
    source_label: str | None = None,
) -> tuple[list[str], list[PatternSource]]:
    """Read and parse a gitignore-format ignore file.

    Extracts patterns from the file, skipping blank lines and comments.
    Leading whitespace is stripped; trailing whitespace is preserved for
    pathspec to handle (important for backslash-escaped trailing spaces
    like ``foo\\ ``).

    Args:
        path: Absolute path to the ignore file.
        source_label: Label for ``PatternSource.file`` entries.
            Defaults to the filename component of ``path``.

    Returns:
        A tuple of ``(patterns, sources)`` where ``patterns[i]``
        corresponds to ``sources[i]``. Returns empty lists if the
        file does not exist or cannot be read.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return [], []
    except (OSError, UnicodeDecodeError):
        logger.debug("Could not read ignore file: %s", path)
        return [], []

    label = source_label or path.name
    patterns: list[str] = []
    sources: list[PatternSource] = []

    for line_no, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.lstrip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
        sources.append(PatternSource(file=label, line=line_no, pattern=line))

    return patterns, sources
