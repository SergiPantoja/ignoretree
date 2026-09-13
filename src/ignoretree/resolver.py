"""Layered ignore-pattern resolver with gitignore-compatible semantics."""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pathspec import GitIgnoreSpec, PathSpec
from pathspec.pattern import Pattern

from ignoretree.models import IgnoreDecision, PatternSource
from ignoretree.reader import read_ignore_file


@dataclass(frozen=True, slots=True)
class _IgnoreLayer:
    """Compiled file and directory views with aligned provenance."""

    file_spec: GitIgnoreSpec
    directory_spec: PathSpec[Pattern]
    sources: list[PatternSource]


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
        default_sources = [
            PatternSource(file="<defaults>", line=None, pattern=p) for p in default_patterns
        ]
        self._default_layer = self._compile_layer(default_patterns, default_sources)

        # Layer 2: .git/info/exclude (repository-level).
        exclude_path = root / ".git" / "info" / "exclude"
        exclude_patterns, exclude_sources = read_ignore_file(
            exclude_path, source_label=".git/info/exclude"
        )
        self._exclude_layer = self._compile_layer(exclude_patterns, exclude_sources)

        # Layer 3: one .gitignore layer per entered directory scope.
        self._gitignore_layers: dict[str, _IgnoreLayer] = {}
        self._entered_dirs: set[str] = set()
        self._pruned_dirs: set[str] = set()

        # Layer 4: custom ignore files from repo root (highest priority).
        custom_patterns: list[str] = []
        custom_sources: list[PatternSource] = []
        for fname in custom_ignore_filenames:
            patterns, sources = read_ignore_file(root / fname, source_label=fname)
            custom_patterns.extend(patterns)
            custom_sources.extend(sources)
        self._custom_layer = self._compile_layer(custom_patterns, custom_sources)

    def enter_directory(self, rel_dir: str) -> None:
        """Register a ``.gitignore`` if one exists in the given directory.

        Call this as you enter each directory during traversal. Ancestor
        scopes are registered first, regardless of call order. If an
        ancestor rule excludes the directory, the scope is recorded as
        pruned and its own ``.gitignore`` is not read. Repeated calls for
        the same directory are safely ignored.

        Args:
            rel_dir: POSIX-style path relative to the repo root.
                Use ``""`` for the repository root itself.
        """
        if rel_dir in self._entered_dirs:
            return

        if rel_dir:
            parent = rel_dir.rpartition("/")[0]
            self.enter_directory(parent)

            # A directory's own ignore file is unreachable when an ancestor
            # source still excludes the directory.
            if self._resolve(rel_dir + "/").ignored:
                self._entered_dirs.add(rel_dir)
                self._pruned_dirs.add(rel_dir)
                return

        self._entered_dirs.add(rel_dir)

        gitignore_path = (
            self._root / rel_dir / ".gitignore" if rel_dir else self._root / ".gitignore"
        )
        source_label = f"{rel_dir}/.gitignore" if rel_dir else ".gitignore"
        patterns, sources = read_ignore_file(gitignore_path, source_label=source_label)
        layer = self._compile_layer(patterns, sources)
        if layer is not None:
            self._gitignore_layers[rel_dir] = layer

    def is_ignored(self, rel_path: str, *, auto_enter: bool = False) -> bool:
        """Check whether a file path should be ignored.

        Evaluates the path against all layers in priority order. The
        last layer whose patterns match determines the result.

        Args:
            rel_path: POSIX-style path relative to the repository root.
            auto_enter: If ``True``, automatically load ``.gitignore``
                files along the ancestor directories of ``rel_path``
                before checking. Useful for one-off checks without
                prior :meth:`enter_directory` or :meth:`load_all` calls.

        Returns:
            ``True`` if the path should be ignored.
        """
        if auto_enter:
            self._enter_ancestors(rel_path)
        return self._resolve(rel_path).ignored

    def is_dir_ignored(self, rel_dir: str, *, auto_enter: bool = False) -> bool:
        """Check whether a directory matches an ignore pattern.

        Appends a trailing ``/`` so that directory-only patterns
        (e.g., ``build/``) match correctly.  Commonly used to prune
        ignored subtrees during traversal.

        Content-only patterns like ``folder/*`` do not match the
        directory itself, so ``is_dir_ignored`` returns ``False`` and
        no pruning happens.

        Args:
            rel_dir: POSIX-style directory path relative to the repo root.
            auto_enter: If ``True``, automatically load ``.gitignore``
                files along the ancestor directories before checking.

        Returns:
            ``True`` if the directory matches an ignore pattern.
        """
        if auto_enter:
            self._enter_ancestors(rel_dir.rstrip("/"))
        return self._resolve(rel_dir.rstrip("/") + "/").ignored

    def explain(self, rel_path: str, *, auto_enter: bool = False) -> IgnoreDecision:
        """Explain why a path is ignored or included.

        Same evaluation as :meth:`is_ignored` but returns an
        :class:`IgnoreDecision` with the winning pattern source.

        Args:
            rel_path: POSIX-style path relative to the repository root.
            auto_enter: If ``True``, automatically load ``.gitignore``
                files along the ancestor directories before checking.

        Returns:
            IgnoreDecision: An object indicating whether the path is ignored
            and which pattern (if any) determined the result.
        """
        if auto_enter:
            self._enter_ancestors(rel_path)
        return self._resolve(rel_path)

    def explain_dir(self, rel_dir: str, *, auto_enter: bool = False) -> IgnoreDecision:
        """Explain why a directory is ignored or included.

        Like :meth:`explain` but appends a trailing ``/`` for
        directory-only pattern matching.

        Args:
            rel_dir: POSIX-style directory path relative to the repo root.
            auto_enter: If ``True``, automatically load ``.gitignore``
                files along the ancestor directories before checking.

        Returns:
            IgnoreDecision: An object indicating whether the path is ignored
            and which pattern (if any) determined the result.
        """
        if auto_enter:
            self._enter_ancestors(rel_dir.rstrip("/"))
        return self._resolve(rel_dir.rstrip("/") + "/")

    def load_all(self) -> None:
        """Discover and load all ``.gitignore`` files in the repository.

        Walks the directory tree starting from root, registering reachable
        ``.gitignore`` files and recording excluded scopes as pruned. After
        this call, :meth:`is_ignored` and :meth:`explain` work for any path
        without additional :meth:`enter_directory` calls.

        Ignored directories are pruned during the walk, so large
        ignored subtrees (``node_modules/``, ``.git/``, etc.) are
        skipped.
        """
        for dirpath, dirnames, _filenames in os.walk(self._root):
            rel_dir = os.path.relpath(dirpath, self._root).replace(os.sep, "/")
            if rel_dir == ".":
                rel_dir = ""

            self.enter_directory(rel_dir)

            # Discover each child once, then prune scopes whose own ignore file
            # is unreachable because the child remains ignored.
            entered_children: list[str] = []
            for dirname in dirnames:
                child = f"{rel_dir}/{dirname}" if rel_dir else dirname
                self.enter_directory(child)
                if child not in self._pruned_dirs:
                    entered_children.append(dirname)
            dirnames[:] = entered_children

    def _enter_ancestors(self, rel_path: str) -> None:
        """Enter all ancestor directories of ``rel_path``."""
        self.enter_directory("")

        parts = rel_path.rstrip("/").split("/")
        for i in range(1, len(parts)):
            ancestor = "/".join(parts[:i])
            self.enter_directory(ancestor)

    def _resolve(self, rel_path: str) -> IgnoreDecision:
        """Evaluate *rel_path*, stopping at the first excluded ancestor."""
        is_directory = rel_path.endswith("/")
        clean_path = rel_path.rstrip("/")

        parts = clean_path.split("/")
        for depth in range(1, len(parts)):
            ancestor = "/".join(parts[:depth])
            decision = self._resolve_exact(ancestor, is_directory=True)
            if decision.ignored:
                return decision

        return self._resolve_exact(clean_path, is_directory=is_directory)

    def _resolve_exact(self, rel_path: str, *, is_directory: bool) -> IgnoreDecision:
        """Resolve one reachable path entry against its applicable scopes."""
        result: bool | None = None
        source: PatternSource | None = None
        match_path = rel_path + "/" if is_directory else rel_path

        # Layer 1: defaults.
        if self._default_layer is not None:
            hit = self._check_layer(self._default_layer, match_path, is_directory=is_directory)
            if hit is not None:
                result, source = hit

        # Layer 2: .git/info/exclude.
        if self._exclude_layer is not None:
            hit = self._check_layer(self._exclude_layer, match_path, is_directory=is_directory)
            if hit is not None:
                result, source = hit

        # Layer 3: only directly applicable scopes, root-to-deepest.
        parts = rel_path.split("/")
        scopes = [""] + ["/".join(parts[:depth]) for depth in range(1, len(parts))]
        for scope in scopes:
            layer = self._gitignore_layers.get(scope)
            if layer is None:
                continue
            scoped = rel_path[len(scope) + 1 :] if scope else rel_path
            scoped_path = scoped + "/" if is_directory else scoped
            hit = self._check_layer(layer, scoped_path, is_directory=is_directory)
            if hit is not None:
                result, source = hit

        # Layer 4: custom ignore files.
        if self._custom_layer is not None:
            hit = self._check_layer(self._custom_layer, match_path, is_directory=is_directory)
            if hit is not None:
                result, source = hit

        return IgnoreDecision(ignored=result is True, source=source)

    @staticmethod
    def _compile_layer(
        patterns: Sequence[str], sources: list[PatternSource]
    ) -> _IgnoreLayer | None:
        """Compile matching views while preserving shared source indexes."""
        if not patterns:
            return None
        return _IgnoreLayer(
            file_spec=GitIgnoreSpec.from_lines(patterns),
            directory_spec=PathSpec.from_lines("gitignore", patterns),
            sources=sources,
        )

    @staticmethod
    def _check_layer(
        layer: _IgnoreLayer, path: str, *, is_directory: bool
    ) -> tuple[bool, PatternSource] | None:
        """Return the matching result and aligned source for one layer."""
        spec = layer.directory_spec if is_directory else layer.file_spec
        check = spec.check_file(path)
        if check.include is None:
            return None
        if check.index is None:
            # Mypy doesnt know that check.include and check.index are linked and
            # index can only be None if include is None. This error should never
            # happen at runtime.
            raise TypeError("pathspec returned include without index")
        return check.include, layer.sources[check.index]
