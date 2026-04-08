"""Show which pattern is responsible for each ignore decision.

Usage:
    python examples/explain_decisions.py /path/to/repo
"""

import os
import sys
from pathlib import Path

from ignoretree import IgnoreResolver

DEFAULT_PATTERNS = ["*.pyc", "__pycache__/", ".git/"]


def explain_decisions(root: Path) -> None:
    resolver = IgnoreResolver(
        root=root,
        default_patterns=DEFAULT_PATTERNS,
    )

    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root).replace(os.sep, "/")
        if rel_dir == ".":
            rel_dir = ""

        resolver.enter_directory(rel_dir)

        # Prune ignored directories, but explain why.
        kept = []
        for d in sorted(dirnames):
            rel = f"{rel_dir}/{d}" if rel_dir else d
            decision = resolver.explain_dir(rel)
            if decision.ignored:
                src = decision.source
                origin = f"{src.file}:{src.line} ({src.pattern})" if src else "unknown"
                print(f"  SKIP  {rel}/  [{origin}]")
            else:
                kept.append(d)
        dirnames[:] = kept

        for fname in sorted(filenames):
            rel_path = f"{rel_dir}/{fname}" if rel_dir else fname
            decision = resolver.explain(rel_path)
            if decision.ignored:
                src = decision.source
                origin = f"{src.file}:{src.line} ({src.pattern})" if src else "unknown"
                print(f"  SKIP  {rel_path}  [{origin}]")
            else:
                print(f"  KEEP  {rel_path}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <repo-root>", file=sys.stderr)
        sys.exit(1)
    explain_decisions(Path(sys.argv[1]).resolve())
