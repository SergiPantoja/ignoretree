# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- `explain()` and `explain_dir()` for debug traceability — returns the winning `PatternSource` (file, line, pattern) that determined the ignore decision.

## [0.1.0] - 2026-04-06

### Added

- `IgnoreResolver` with four-layer precedence system (defaults < .git/info/exclude < .gitignore < custom ignore files).
- `is_ignored()` and `is_dir_ignored()` for file and directory ignore checking.
- `enter_directory()` for incremental `.gitignore` loading during traversal.
- `read_ignore_file()` with correct whitespace handling and pattern source tracking.
- `PatternSource` and `IgnoreDecision` data classes for structured results.
- GitIgnoreSpec backend for accurate gitignore semantics.
- Git compliance test suite validated against git 2.48–2.53.

[0.1.0]: https://github.com/SergiPantoja/ignoretree/releases/tag/v0.1.0
