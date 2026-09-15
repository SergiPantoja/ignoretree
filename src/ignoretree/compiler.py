"""Shared compilation for patterns from every ignore source."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

from pathspec import GitIgnoreSpec, PathSpec
from pathspec.pattern import Pattern
from pathspec.patterns.gitignore import GitIgnorePatternError

from ignoretree.models import PatternSource

_ASCII_CASE_TRANSLATION = str.maketrans(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ",
    "abcdefghijklmnopqrstuvwxyz",
)


def fold_ascii_case(value: str) -> str:
    """Lowercase ASCII letters without changing any other code point."""
    return value.translate(_ASCII_CASE_TRANSLATION)


@dataclass(frozen=True, slots=True)
class CompiledIgnoreLayer:
    """Compiled file and directory views with aligned provenance."""

    file_spec: GitIgnoreSpec
    directory_spec: PathSpec[Pattern]
    sources: list[PatternSource]


def compile_ignore_patterns(
    patterns: Sequence[str],
    sources: Sequence[PatternSource],
    *,
    case_sensitive: bool = True,
) -> CompiledIgnoreLayer | None:
    """Compile valid Git patterns while discarding malformed and no-op rules.

    ``GitIgnoreSpec`` is used as the validator because its pattern factory
    recognizes Git no-ops that the generic ``PathSpec`` factory may compile as
    active patterns. Patterns are validated one at a time so one bad rule does
    not prevent later valid rules from applying. Case-insensitive compilation
    folds only ASCII letters and leaves the original source records unchanged.
    """
    valid_patterns: list[str] = []
    valid_sources: list[PatternSource] = []

    for pattern, source in zip(patterns, sources, strict=True):
        compiled_pattern = pattern if case_sensitive else fold_ascii_case(pattern)
        try:
            probe = GitIgnoreSpec.from_lines([compiled_pattern])
        except (GitIgnorePatternError, re.error):
            continue

        if not probe.patterns or probe.patterns[0].include is None:
            continue

        valid_patterns.append(compiled_pattern)
        valid_sources.append(source)

    if not valid_patterns:
        return None

    return CompiledIgnoreLayer(
        file_spec=GitIgnoreSpec.from_lines(valid_patterns),
        directory_spec=PathSpec.from_lines("gitignore", valid_patterns),
        sources=valid_sources,
    )
