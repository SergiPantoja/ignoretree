"""Walk a repository tree, skipping ignored files and directories.

Usage:
    python examples/walk_tree.py /path/to/repo
"""

import os
import sys
from pathlib import Path

from ignoretree import IgnoreResolver

DEFAULT_PATTERNS = ["*.pyc", "__pycache__/", ".git/"]


def walk_tree(root: Path) -> None:
    resolver = IgnoreResolver(
        root=root,
        default_patterns=DEFAULT_PATTERNS,
    )

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""

        resolver.enter_directory(rel_dir)

        # Prune ignored directories so os.walk doesn't descend into them.
        dirnames[:] = sorted(
            d for d in dirnames if not resolver.is_dir_ignored(f"{rel_dir}/{d}" if rel_dir else d)
        )

        for fname in sorted(filenames):
            rel_path = f"{rel_dir}/{fname}" if rel_dir else fname
            if not resolver.is_ignored(rel_path):
                print(rel_path)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <repo-root>", file=sys.stderr)
        sys.exit(1)
    walk_tree(Path(sys.argv[1]).resolve())
