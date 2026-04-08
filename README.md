# ignoretree

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
import os
from pathlib import Path

from ignoretree import IgnoreResolver

root = Path("/path/to/repo")
resolver = IgnoreResolver(
    root=root,
    default_patterns=["*.pyc", "__pycache__/", ".git/"], # optional
    custom_ignore_filenames=[".myignore"],  # optional
)

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

> Note: You can use `Path.walk()` instead of `os.walk()` in Python 3.12+

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
