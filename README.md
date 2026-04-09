# ignoretree

[![CI](https://github.com/SergiPantoja/ignoretree/actions/workflows/ci.yml/badge.svg)](https://github.com/SergiPantoja/ignoretree/actions/workflows/ci.yml)
[![PyPI - Version](https://img.shields.io/pypi/v/ignoretree)](https://pypi.org/project/ignoretree/)
![PyPI - Python Version](https://img.shields.io/pypi/pyversions/ignoretree)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Layered gitignore-compatible ignore pattern resolution for Python.

I built this because I needed to resolve ignore patterns across multiple layers (default patterns, `.gitignore`, `.git/info/exclude`, custom ignore files) in my projects, and couldn't find a library that did that. [pathspec](https://github.com/cpburnz/python-pathspec) handles pattern matching well, but you're on your own for layered precedence, nested `.gitignore` scoping, and figuring out *which* pattern caused a file to be ignored.

## Features

- Four-layer precedence: defaults < `.git/info/exclude` < `.gitignore` (root to deepest) < custom ignore files. Last match wins.
- Nested `.gitignore` files are scoped to their directory, matching git behavior.
- `explain()` tells you exactly which pattern in which file caused the decision.
- Backed by [pathspec](https://github.com/cpburnz/python-pathspec)'s `GitIgnoreSpec` for correct gitignore semantics.
- Fully typed (PEP 561).

## Installation

```bash
pip install ignoretree
```
Or with uv:

```bash
uv add ignoretree
```

Requires Python 3.11+.

## Quick Start

```python
from pathlib import Path
from ignoretree import IgnoreResolver

resolver = IgnoreResolver(
    root=Path("/path/to/repo"),
    default_patterns=["*.pyc", "__pycache__/", ".git/"],  # optional
    custom_ignore_filenames=[".myignore"],  # optional
)

# Check a single file (`auto_enter=True` loads .gitignore files along the path automatically):
resolver.is_ignored("src/debug.log", auto_enter=True)  # True or False
```

### Bulk load

If you're going to check many files, load all `.gitignore` files upfront:

```python
resolver.load_all()  # walks the repo, discovers all .gitignore files

resolver.is_ignored("src/debug.log")
resolver.is_ignored("tests/conftest.py")
```

### Walker integration

For full control during directory traversal, call `enter_directory()` as you go. This lets you prune ignored directories so `os.walk` doesn't descend into them:

```python
import os

root = Path("/path/to/repo")
resolver = IgnoreResolver(root, default_patterns=["*.pyc", "__pycache__/", ".git/"])

for dirpath, dirnames, filenames in os.walk(root):
    rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
    if rel_dir == ".":
        rel_dir = ""

    resolver.enter_directory(rel_dir)

    # Prune ignored directories so os.walk doesn't descend into them.
    dirnames[:] = [
        d for d in dirnames
        if not resolver.is_dir_ignored(f"{rel_dir}/{d}" if rel_dir else d)
    ]

    for fname in filenames:
        rel_path = f"{rel_dir}/{fname}" if rel_dir else fname
        if not resolver.is_ignored(rel_path):
            print(rel_path)
```

> On Python 3.12+, you can use `Path.walk()` instead of `os.walk()`.

### Debugging with `explain()`

When you need to know *why* a file is ignored (or not):

```python
decision = resolver.explain("src/debug.log")
print(decision)
# IgnoreDecision(ignored=True, source=PatternSource(file='.gitignore', line=3, pattern='*.log'))

decision = resolver.explain("src/main.py")
print(decision)
# IgnoreDecision(ignored=False, source=None)
```

Both `explain()` and `explain_dir()` return an `IgnoreDecision` with the winning pattern source. They also support `auto_enter=True` for on-demand loading.

Works well with standard logging:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

for path in paths_to_check:
    decision = resolver.explain(path)
    logger.debug(f"Ignore decision for {path}: {decision}")
```

See the [examples/](examples/) directory for runnable scripts.

## Usage Modes

| Mode | Method | When to use |
|------|--------|-------------|
| On-demand | `is_ignored(..., auto_enter=True)` | Checking one or a few files. Loads `.gitignore` files along the path on demand. |
| Bulk | `load_all()` + `is_ignored()` | Checking many files. Discovers all `.gitignore` files upfront. |
| Walker | `enter_directory()` + `is_ignored()` | During `os.walk()` traversal. Maximum control over pruning. |

All three modes support defaults, `.git/info/exclude`, nested `.gitignore` scoping, and custom ignore files. The difference is how and when `.gitignore` files are loaded.

## Layer Precedence

Patterns are evaluated across four layers, from lowest to highest priority:

| Priority | Layer | Source |
|----------|-------|--------|
| 1 (lowest) | Defaults | `default_patterns` argument |
| 2 | Exclude | `.git/info/exclude` |
| 3 | Gitignore | `.gitignore` files (root to deepest directory) |
| 4 (highest) | Custom | Files listed in `custom_ignore_filenames` |

Within each layer, negation patterns (`!`) work per gitignore rules. Across layers, the last layer with a matching pattern wins.

## Development

Clone and install dependencies:

```bash
git clone https://github.com/SergiPantoja/ignoretree.git
cd ignoretree
uv sync
```

### Running checks

```bash
uv run pytest                          # tests with coverage
uv run ruff check src/ tests/         # lint
uv run ruff format --check src/ tests/ # format check
uv run mypy src/                       # type check
```

### Pre-commit hooks (optional)

If you tend to forget (like me) to run linting before committing:

```bash
uv run pre-commit install
```

This sets up hooks that run ruff (lint + format) and check `uv.lock` consistency on every commit.

### Code style

- [Ruff](https://docs.astral.sh/ruff/) for linting and formatting.
- [Google-style docstrings](https://google.github.io/styleguide/pyguide.html#38-comments-and-docstrings).
- [mypy](https://mypy-lang.org/) in strict mode.

## License

[MIT](LICENSE)
