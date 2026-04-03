"""Layered ignore-pattern resolver with gitignore-compatible semantics."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pathspec import GitIgnoreSpec

from ignoretree.models import PatternSource
from ignoretree.reader import read_ignore_file


class IgnoreResolver:
    """Layered ignore-pattern resolver with gitignore-compatible semantics.

    Manages four layers of ignore patterns, checked in ascending
    priority order (last match wins):

    1. **Defaults** — caller-provided patterns (lowest priority).
    2. **.git/info/exclude** — repository-level exclude patterns.
    3. **.gitignore** — per-directory files, scoped to their
       respective directories (root to deepest).
    4. **Custom** — user-edited ignore files from the repository
       root (highest priority).

    Within each layer, negation patterns (``!``) override earlier
    positive patterns per gitignore semantics. Across layers, the
    last layer whose patterns match determines the result.

    Args:
        root: Absolute path to the repository root.
        default_patterns: Patterns treated as lowest-priority defaults.
            Empty by default — the library assumes nothing about what
            callers want to ignore.
        custom_ignore_filenames: Names of custom ignore files to look
            for in the repository root. Empty by default.

    Example::

        resolver = IgnoreResolver(
            root=Path("/repo"),
            default_patterns=["*.pyc", "__pycache__/"],
        )
        resolver.enter_directory("")
        resolver.is_ignored("cache.pyc")  # True
    """

    def __init__(
        self,
        root: Path,
        default_patterns: Sequence[str] = (),
        custom_ignore_filenames: Sequence[str] = (),
    ) -> None:
        self._root = root

        # Layer 1: caller-provided defaults (lowest priority).
        self._default_sources: list[PatternSource] = [
            PatternSource(file="<defaults>", line=None, pattern=p) for p in default_patterns
        ]
        self._default_spec: GitIgnoreSpec | None = (
            GitIgnoreSpec.from_lines(default_patterns) if default_patterns else None
        )

        # Layer 2: .git/info/exclude (repository-level).
        exclude_path = root / ".git" / "info" / "exclude"
        exclude_patterns, self._exclude_sources = read_ignore_file(
            exclude_path, source_label=".git/info/exclude"
        )
        self._exclude_spec: GitIgnoreSpec | None = (
            GitIgnoreSpec.from_lines(exclude_patterns) if exclude_patterns else None
        )

        # Layer 3: .gitignore layers, accumulated via enter_directory().
        self._gitignore_layers: list[tuple[str, GitIgnoreSpec, list[PatternSource]]] = []
        self._entered_dirs: set[str] = set()

        # Layer 4: custom ignore files from repo root (highest priority).
        custom_patterns: list[str] = []
        custom_sources: list[PatternSource] = []
        for fname in custom_ignore_filenames:
            patterns, sources = read_ignore_file(root / fname, source_label=fname)
            custom_patterns.extend(patterns)
            custom_sources.extend(sources)
        self._custom_sources = custom_sources
        self._custom_spec: GitIgnoreSpec | None = (
            GitIgnoreSpec.from_lines(custom_patterns) if custom_patterns else None
        )

    def enter_directory(self, rel_dir: str) -> None:
        """Register a ``.gitignore`` if one exists in the given directory.

        Called by the scanner as it enters each directory during
        traversal. If a ``.gitignore`` file is found, its patterns are
        stored as a new layer scoped to ``rel_dir``. Repeated calls
        for the same directory are safely ignored.

        Args:
            rel_dir: POSIX-style path relative to the repo root.
                Use ``""`` for the repository root itself.
        """
        if rel_dir in self._entered_dirs:
            return
        self._entered_dirs.add(rel_dir)

        gitignore_path = (
            self._root / rel_dir / ".gitignore" if rel_dir else self._root / ".gitignore"
        )
        source_label = f"{rel_dir}/.gitignore" if rel_dir else ".gitignore"
        patterns, sources = read_ignore_file(gitignore_path, source_label=source_label)
        if patterns:
            self._gitignore_layers.append((rel_dir, GitIgnoreSpec.from_lines(patterns), sources))

    def is_ignored(self, rel_path: str) -> bool:
        """Check whether a file path should be ignored.

        Evaluates the path against all layers in priority order. The
        last layer whose patterns match determines the result.

        Args:
            rel_path: POSIX-style path relative to the repository root.

        Returns:
            ``True`` if the path should be ignored.
        """
        result: bool | None = None

        # Layer 1: defaults.
        if self._default_spec is not None:
            decision = self._check_spec(self._default_spec, rel_path)
            if decision is not None:
                result = decision

        # Layer 2: .git/info/exclude.
        if self._exclude_spec is not None:
            decision = self._check_spec(self._exclude_spec, rel_path)
            if decision is not None:
                result = decision

        # Layer 3: .gitignore layers (root-to-deepest).
        for dir_prefix, spec, _sources in self._gitignore_layers:
            if not dir_prefix or rel_path.startswith(dir_prefix + "/"):
                scoped = rel_path[len(dir_prefix) + 1 :] if dir_prefix else rel_path
                decision = self._check_spec(spec, scoped)
                if decision is not None:
                    result = decision

        # Layer 4: custom ignore files.
        if self._custom_spec is not None:
            decision = self._check_spec(self._custom_spec, rel_path)
            if decision is not None:
                result = decision

        return result is True

    def is_dir_ignored(self, rel_dir: str) -> bool:
        """Check whether a directory should be pruned from traversal.

        Appends a trailing ``/`` so that directory-only gitignore
        patterns (e.g., ``build/``) match correctly.

        Args:
            rel_dir: POSIX-style directory path relative to the repo root.

        Returns:
            ``True`` if the directory should be pruned.
        """
        return self.is_ignored(rel_dir.rstrip("/") + "/")

    @staticmethod
    def _check_spec(spec: GitIgnoreSpec, path: str) -> bool | None:
        """Return the ignore decision from a single spec layer."""
        return spec.check_file(path).include
