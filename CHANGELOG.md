# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Added the keyword-only `case_sensitive` resolver option for explicit compatibility with Git repositories that use `core.ignoreCase=true`. It defaults to case-sensitive matching and uses ASCII-only folding when disabled.

### Changed

- Replaced the independent Git compliance checks with differential tests that compare Git decisions and provenance against all ignoretree usage modes.
- Git test failures now reject unexpected `git check-ignore` exit codes instead of treating them as nonmatches.
- Raised the minimum supported `pathspec` version to 1.1.0.
- Made completed `load_all()` calls stable snapshots so repeated calls do not walk the repository again.

### Migration notes

- Path APIs now require canonical root-relative POSIX strings. Callers passing path-like objects, absolute paths, backslashes, repeated separators, or `.` and `..` components must normalize them first.
- Negation rules no longer re-include a path while one of its parent directories remains ignored. Add negation rules for each ignored parent directory to make descendants eligible again.

### Fixed

- Enforced Git's ignored-parent rule across defaults, exclude files, nested `.gitignore` files, and custom ignore files.
- Made directory-only negations work correctly for traversal decisions.
- Made nested `.gitignore` precedence independent of manual `enter_directory()` call order and prevented loading ignore files below excluded directories.
- Enforced canonical root-relative string paths and safe custom ignore basenames before matching or filesystem access.
- Prevented `.gitignore`, exclude, and custom ignore-file discovery from escaping the resolved root through symlinks.
- Preserved significant leading whitespace and accepted a UTF-8 BOM at the start of ignore files.
- Made malformed and Git no-op patterns harmless so later valid rules still apply.
- Loaded the effective common `.git/info/exclude` rules in linked Git worktrees and submodule-style layouts.
- Prevented `load_all()` from traversing directories named `.git` without requiring a caller-provided ignore rule.

## [0.2.0] - 2026-04-08

### Added

- `explain()` and `explain_dir()` for debug traceability — returns the winning `PatternSource` (file, line, pattern) that determined the ignore decision.
- `load_all()` for bulk `.gitignore` discovery — walks the repo tree and loads all `.gitignore` files upfront, with pruning of ignored directories.
- `auto_enter` keyword parameter on `is_ignored()`, `is_dir_ignored()`, `explain()`, `explain_dir()` — when `True`, loads only the ancestor `.gitignore` files needed for the queried path on demand.

## [0.1.0] - 2026-04-06

### Added

- `IgnoreResolver` with four-layer precedence system (defaults < .git/info/exclude < .gitignore < custom ignore files).
- `is_ignored()` and `is_dir_ignored()` for file and directory ignore checking.
- `enter_directory()` for incremental `.gitignore` loading during traversal.
- `read_ignore_file()` with correct whitespace handling and pattern source tracking.
- `PatternSource` and `IgnoreDecision` data classes for structured results.
- GitIgnoreSpec backend for accurate gitignore semantics.
- Git compliance test suite validated against git 2.48–2.53.

[Unreleased]: https://github.com/SergiPantoja/ignoretree/compare/v0.2.0...HEAD
[0.1.0]: https://github.com/SergiPantoja/ignoretree/releases/tag/v0.1.0
[0.2.0]: https://github.com/SergiPantoja/ignoretree/releases/tag/v0.2.0
