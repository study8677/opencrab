"""Small pure-function trial for code-level weaning.

This module is intentionally dependency-free and side-effect-free.  It gives the
project a tiny, testable piece of live Python code that can be compiled,
imported, and checked without relying on external tools.
"""

from __future__ import annotations

from typing import Iterable, Mapping, Sequence


def bounded_ratio(done: int | float, total: int | float, *, digits: int = 6) -> float:
    """Return ``done / total`` rounded and clamped into ``[0.0, 1.0]``.

    The function is deliberately conservative for low-risk reuse:

    * non-positive totals return ``0.0`` instead of raising ``ZeroDivisionError``;
    * negative progress is clamped to ``0.0``;
    * over-complete progress is clamped to ``1.0``;
    * rounding is stable and controlled by ``digits``.
    """

    if total <= 0:
        return 0.0

    ratio = done / total
    if ratio <= 0:
        return 0.0
    if ratio >= 1:
        return 1.0
    return round(float(ratio), digits)


def bounded_ratio_cases() -> tuple[tuple[int | float, int | float, float], ...]:
    """Regression cases used as in-repo evidence for ``bounded_ratio``."""

    return (
        (0, 0, 0.0),
        (1, 0, 0.0),
        (-1, 4, 0.0),
        (1, 4, 0.25),
        (2, 3, 0.666667),
        (4, 4, 1.0),
        (5, 4, 1.0),
    )


def check_bounded_ratio(cases: Iterable[Sequence[int | float]] | None = None) -> bool:
    """Return ``True`` when all supplied regression cases pass.

    Each case is ``(done, total, expected)``.  The return value keeps this helper
    pure and caller-controlled; it performs no printing, file writes, or exits.
    """

    selected = bounded_ratio_cases() if cases is None else cases
    return all(bounded_ratio(case[0], case[1]) == case[2] for case in selected)


def evidence() -> Mapping[str, object]:
    """Return compact evidence that this pure-function trial is healthy."""

    return {
        "subject": "bounded_ratio",
        "kind": "brain_only_low_risk_pure_function",
        "case_count": len(bounded_ratio_cases()),
        "regression_passed": check_bounded_ratio(),
    }


__all__ = [
    "bounded_ratio",
    "bounded_ratio_cases",
    "check_bounded_ratio",
    "evidence",
]
