"""Data models for ignore pattern resolution."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class PatternSource:
    """Records where an ignore pattern originated.

    Attributes:
        file: Relative path or label of the source
            (e.g., ``".gitignore"``, ``"src/.gitignore"``, ``"<defaults>"``).
        line: 1-based line number in the source file, or ``None`` for
            programmatic patterns (e.g., defaults).
        pattern: The raw pattern text as parsed from the source.
    """

    file: str
    line: int | None
    pattern: str


@dataclass(frozen=True, slots=True)
class IgnoreDecision:
    """Result of an ignore check with source tracking.

    Attributes:
        ignored: Whether the path is ignored.
        source: The pattern that determined the result, or ``None`` if
            no pattern matched the path.
    """

    ignored: bool
    source: PatternSource | None
