"""Tests for shared ignore-pattern compilation."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from ignoretree.compiler import compile_ignore_patterns
from ignoretree.models import PatternSource


def _sources(patterns: list[str]) -> list[PatternSource]:
    return [
        PatternSource(file=".gitignore", line=line, pattern=pattern)
        for line, pattern in enumerate(patterns, start=1)
    ]


def test_discards_malformed_and_git_no_op_patterns() -> None:
    patterns = ["!", "trailing\\", "[z-a]", "[", "/", "*.log"]

    layer = compile_ignore_patterns(patterns, _sources(patterns))

    assert layer is not None
    assert layer.file_spec.match_file("debug.log") is True
    assert layer.directory_spec.match_file("[") is False
    assert layer.sources == [PatternSource(file=".gitignore", line=6, pattern="*.log")]


def test_returns_none_when_every_pattern_is_a_no_op() -> None:
    patterns = ["", "   ", "!", "/", "["]

    assert compile_ignore_patterns(patterns, _sources(patterns)) is None


def test_rejects_misaligned_pattern_sources() -> None:
    with pytest.raises(ValueError, match=r"zip\(\) argument 2 is shorter"):
        compile_ignore_patterns(["*.log"], [])


def test_does_not_swallow_unexpected_compiler_errors() -> None:
    source = PatternSource(file=".gitignore", line=1, pattern="*.log")

    with (
        patch(
            "ignoretree.compiler.GitIgnoreSpec.from_lines",
            side_effect=RuntimeError("unexpected"),
        ),
        pytest.raises(RuntimeError, match="unexpected"),
    ):
        compile_ignore_patterns(["*.log"], [source])


def test_case_insensitive_compilation_folds_only_ascii_and_preserves_sources() -> None:
    patterns = ["FILE.TXT", "straße.TXT"]

    layer = compile_ignore_patterns(patterns, _sources(patterns), case_sensitive=False)

    assert layer is not None
    assert layer.file_spec.match_file("file.txt") is True
    assert layer.file_spec.match_file("straße.txt") is True
    assert layer.file_spec.match_file("STRASSE.txt") is False
    assert layer.sources == _sources(patterns)
