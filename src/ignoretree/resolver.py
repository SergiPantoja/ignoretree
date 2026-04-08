"""Layered ignore-pattern resolver with gitignore-compatible semantics."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pathspec import GitIgnoreSpec

from ignoretree.models import IgnoreDecision, PatternSource
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
            Empty by default.
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

        Call this as you enter each directory during traversal. If a
        ``.gitignore`` file is found, its patterns are stored as a new
        layer scoped to ``rel_dir``. Repeated calls for the same
        directory are safely ignored.

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
        return self._resolve(rel_path).ignored

    def is_dir_ignored(self, rel_dir: str) -> bool:
        """Check whether a directory matches an ignore pattern.

        Appends a trailing ``/`` so that directory-only patterns
        (e.g., ``build/``) match correctly.  Commonly used to prune
        ignored subtrees during traversal.

        Content-only patterns like ``folder/*`` do not match the
        directory itself, so ``is_dir_ignored`` returns ``False`` and
        no pruning happens.

        Args:
            rel_dir: POSIX-style directory path relative to the repo root.

        Returns:
            ``True`` if the directory matches an ignore pattern.
        """
        return self.is_ignored(rel_dir.rstrip("/") + "/")

    def explain(self, rel_path: str) -> IgnoreDecision:
        """Explain why a path is ignored or included.

        Same evaluation as :meth:`is_ignored` but returns an
        :class:`IgnoreDecision` with the winning pattern source.

        Args:
            rel_path: POSIX-style path relative to the repository root.

        Returns:
            ``IgnoreDecision`` An object indicating whether the path is
            ignored and which pattern (if any) determined the result.
        """
        return self._resolve(rel_path)

    def explain_dir(self, rel_dir: str) -> IgnoreDecision:
        """Explain why a directory is ignored or included.

        Like :meth:`explain` but appends a trailing ``/`` for
        directory-only pattern matching.

        Args:
            rel_dir: POSIX-style directory path relative to the repo root.

        Returns:
            ``IgnoreDecision`` with source information.
        """
        return self._resolve(rel_dir.rstrip("/") + "/")

    def _resolve(self, rel_path: str) -> IgnoreDecision:
        """Evaluate *rel_path* against all layers and return the decision."""
        result: bool | None = None
        source: PatternSource | None = None

        # Layer 1: defaults.
        if self._default_spec is not None:
            hit = self._check_spec(self._default_spec, rel_path, self._default_sources)
            if hit is not None:
                result, source = hit

        # Layer 2: .git/info/exclude.
        if self._exclude_spec is not None:
            hit = self._check_spec(self._exclude_spec, rel_path, self._exclude_sources)
            if hit is not None:
                result, source = hit

        # Layer 3: .gitignore layers (root-to-deepest).
        for dir_prefix, spec, layer_sources in self._gitignore_layers:
            if not dir_prefix or rel_path.startswith(dir_prefix + "/"):
                scoped = rel_path[len(dir_prefix) + 1 :] if dir_prefix else rel_path
                hit = self._check_spec(spec, scoped, layer_sources)
                if hit is not None:
                    result, source = hit

        # Layer 4: custom ignore files.
        if self._custom_spec is not None:
            hit = self._check_spec(self._custom_spec, rel_path, self._custom_sources)
            if hit is not None:
                result, source = hit

        return IgnoreDecision(ignored=result is True, source=source)

    @staticmethod
    def _check_spec(
        spec: GitIgnoreSpec, path: str, sources: list[PatternSource]
    ) -> tuple[bool, PatternSource] | None:
        """Return ``(include, source)`` if the spec matched, else ``None``."""
        check = spec.check_file(path)
        if check.include is None:
            return None
        if check.index is None:
            # Mypy doesnt know that check.include and check.index are linked and
            # index can only be None if include is None. This error should never
            # happen at runtime.
            raise TypeError("pathspec returned include without index")
        return check.include, sources[check.index]
