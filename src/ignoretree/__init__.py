"""Layered gitignore-compatible ignore pattern resolution for Python."""

from importlib.metadata import version

from ignoretree.models import IgnoreDecision, PatternSource
from ignoretree.resolver import IgnoreResolver

__all__ = ["IgnoreDecision", "IgnoreResolver", "PatternSource"]
__version__ = version("ignoretree")
