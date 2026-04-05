"""Layered gitignore-compatible ignore pattern resolution for Python."""

from ignoretree.models import IgnoreDecision, PatternSource
from ignoretree.resolver import IgnoreResolver

__all__ = ["IgnoreDecision", "IgnoreResolver", "PatternSource"]
__version__ = "0.1.0"
