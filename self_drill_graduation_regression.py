"""Regression checks for the self-contained graduation drill."""

from __future__ import annotations

import tempfile
from pathlib import Path

from self_drill_graduation import (
    astlocator_first_definition,
    patchfitroom_unique_replace,
    regression_compile,
)


def test_astlocator_first_definition_finds_function() -> None:
    kind, name = astlocator_first_definition("def sample():\n    return 1\n")
    assert (kind, name) == ("function", "sample")


def test_patchfitroom_unique_replace_rejects_ambiguous_text() -> None:
    try:
        patchfitroom_unique_replace("x x", "x", "y")
    except ValueError as exc:
        assert "occurrences=2" in str(exc)
    else:
        raise AssertionError("ambiguous patch should be rejected")


def test_regression_compile_accepts_valid_python() -> None:
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "candidate.py"
        path.write_text("VALUE = 1\n", encoding="utf-8")
        assert regression_compile((path,)) is True
