"""Tests for the explicit case-sensitivity policy."""

from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from ignoretree import IgnoreDecision, IgnoreResolver, PatternSource
from ignoretree.reader import read_ignore_file


def test_case_sensitive_is_keyword_only_and_defaults_to_true(tmp_path: Path) -> None:
    parameter = inspect.signature(IgnoreResolver).parameters["case_sensitive"]

    assert parameter.kind is inspect.Parameter.KEYWORD_ONLY
    assert parameter.default is True
    with pytest.raises(TypeError):
        IgnoreResolver(tmp_path, (), (), False)  # type: ignore[call-arg]


def test_default_policy_preserves_case_sensitive_behavior(tmp_path: Path) -> None:
    resolver = IgnoreResolver(tmp_path, default_patterns=["FILE.TXT"])

    assert resolver.is_ignored("FILE.TXT") is True
    assert resolver.is_ignored("file.txt") is False


def test_case_insensitive_policy_applies_to_every_source(tmp_path: Path) -> None:
    (tmp_path / ".git" / "info").mkdir(parents=True)
    (tmp_path / ".git" / "info" / "exclude").write_text("EXCLUDE.TWO\n")
    (tmp_path / ".gitignore").write_text("/ROOT.THREE\n")
    (tmp_path / "Scope").mkdir()
    (tmp_path / "Scope" / ".gitignore").write_text("NESTED.FOUR\n")
    (tmp_path / ".custom").write_text("CUSTOM.FIVE\n")
    resolver = IgnoreResolver(
        tmp_path,
        default_patterns=["DEFAULT.ONE"],
        custom_ignore_filenames=[".custom"],
        case_sensitive=False,
    )
    resolver.enter_directory("Scope")

    assert resolver.explain("default.one") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file="<defaults>", line=None, pattern="DEFAULT.ONE"),
    )
    assert resolver.explain("exclude.two") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file=".git/info/exclude", line=1, pattern="EXCLUDE.TWO"),
    )
    assert resolver.explain("root.three") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file=".gitignore", line=1, pattern="/ROOT.THREE"),
    )
    assert resolver.explain("scope/nested.four") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file="Scope/.gitignore", line=1, pattern="NESTED.FOUR"),
    )
    assert resolver.explain("custom.five") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file=".custom", line=1, pattern="CUSTOM.FIVE"),
    )


def test_ascii_case_folding_does_not_fold_non_ascii_or_normalize_unicode(
    tmp_path: Path,
) -> None:
    resolver = IgnoreResolver(
        tmp_path,
        default_patterns=["Unicode-ß.txt", "straße.txt", "CAFÉ-one.txt", "café-two.TXT"],
        case_sensitive=False,
    )

    assert resolver.is_ignored("unicode-ß.txt") is True
    assert resolver.is_ignored("STRASSE.txt") is False
    assert resolver.is_ignored("café-one.txt") is False
    assert resolver.is_ignored("cafe\u0301-two.txt") is False


def test_manual_scope_keys_use_ascii_case_folding(tmp_path: Path) -> None:
    (tmp_path / "Scope").mkdir()
    (tmp_path / "Scope" / ".gitignore").write_text("/FILE.TXT\n")
    resolver = IgnoreResolver(tmp_path, case_sensitive=False)

    with patch("ignoretree.resolver.read_ignore_file", wraps=read_ignore_file) as reader:
        resolver.enter_directory("Scope")
        resolver.enter_directory("scope")

    scope_ignore = tmp_path / "Scope" / ".gitignore"
    assert sum(call.args[0] == scope_ignore for call in reader.call_args_list) == 1
    assert resolver.explain("scope/file.txt") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file="Scope/.gitignore", line=1, pattern="/FILE.TXT"),
    )

    bulk_resolver = IgnoreResolver(tmp_path, case_sensitive=False)
    bulk_resolver.load_all()
    assert bulk_resolver.explain("SCOPE/file.txt") == IgnoreDecision(
        ignored=True,
        source=PatternSource(file="Scope/.gitignore", line=1, pattern="/FILE.TXT"),
    )


def test_mixed_case_discovery_on_case_insensitive_filesystems(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    scope = root / "Scope"
    scope.mkdir(parents=True)
    (scope / ".gitignore").write_text("*.TXT\n")
    if not (root / "scope").exists():
        pytest.skip("filesystem is case-sensitive")

    resolver = IgnoreResolver(root, case_sensitive=False)

    assert resolver.is_ignored("SCOPE/file.txt", auto_enter=True) is True


def test_external_mypy_consumer_accepts_only_keyword_case_policy(tmp_path: Path) -> None:
    valid = tmp_path / "valid.py"
    invalid = tmp_path / "invalid.py"
    valid.write_text(
        "from pathlib import Path\n"
        "from ignoretree import IgnoreResolver\n"
        "resolver = IgnoreResolver(Path('.'), case_sensitive=False)\n"
        "reveal_type(resolver)\n"
    )
    invalid.write_text(
        "from pathlib import Path\n"
        "from ignoretree import IgnoreResolver\n"
        "IgnoreResolver(Path('.'), (), (), False)\n"
    )

    valid_result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(valid)],
        capture_output=True,
        text=True,
    )
    invalid_result = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", str(invalid)],
        capture_output=True,
        text=True,
    )

    assert valid_result.returncode == 0, valid_result.stdout + valid_result.stderr
    assert "ignoretree.resolver.IgnoreResolver" in valid_result.stdout
    assert invalid_result.returncode == 1
    assert 'Too many positional arguments for "IgnoreResolver"' in invalid_result.stdout
