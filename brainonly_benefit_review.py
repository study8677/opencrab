"""Brain-only landing benefit review.

This module gives the project a small, dependency-free way to revisit the most
recent brain-only self-modification attempts and decide whether a move is
actually paying rent.  It is intentionally conservative: missing evidence,
slow execution, and rollback-heavy results are treated as proof problems rather
than success stories.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from statistics import mean
from typing import Any, Iterable, Mapping, Sequence


DEFAULT_SAMPLE_SIZE = 5
DEFAULT_MAX_ELAPSED_SECONDS = 180.0
DEFAULT_MAX_ROLLBACK_RATE = 0.20


@dataclass(frozen=True)
class BrainOnlyLanding:
    """One brain-only landing attempt to be reviewed."""

    move: str
    evidence: tuple[str, ...] = ()
    elapsed_seconds: float | None = None
    rolled_back: bool = False
    accepted: bool = True
    note: str = ""

    @classmethod
    def from_mapping(cls, item: Mapping[str, Any]) -> "BrainOnlyLanding":
        """Build a landing from loose dict-like telemetry.

        Accepted aliases keep this useful with existing logs:
        - move/name/intent/patch
        - evidence/proofs/checks
        - elapsed_seconds/seconds/duration_s/duration
        - rolled_back/rollback/reverted
        """

        move = str(
            item.get("move")
            or item.get("name")
            or item.get("intent")
            or item.get("patch")
            or "unknown"
        )

        raw_evidence = (
            item.get("evidence")
            if "evidence" in item
            else item.get("proofs", item.get("checks", ()))
        )
        evidence = _coerce_evidence(raw_evidence)

        elapsed_raw = (
            item.get("elapsed_seconds")
            if "elapsed_seconds" in item
            else item.get("seconds", item.get("duration_s", item.get("duration")))
        )
        elapsed_seconds = _coerce_float_or_none(elapsed_raw)

        rolled_back = bool(
            item.get("rolled_back", item.get("rollback", item.get("reverted", False)))
        )
        accepted = bool(item.get("accepted", not rolled_back))
        note = str(item.get("note", item.get("summary", "")))

        return cls(
            move=move,
            evidence=evidence,
            elapsed_seconds=elapsed_seconds,
            rolled_back=rolled_back,
            accepted=accepted,
            note=note,
        )


@dataclass(frozen=True)
class BrainOnlyBenefitReport:
    """Verdict for a sampled set of brain-only landings."""

    sample_size: int
    reviewed: tuple[BrainOnlyLanding, ...]
    missing_evidence: tuple[str, ...]
    slow_moves: tuple[str, ...]
    rollback_rate: float
    average_elapsed_seconds: float | None
    bubble_moves: tuple[str, ...]
    verdict: str
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def reliable(self) -> bool:
        """True when no retirement signal was found."""

        return self.verdict == "keep"


def review_recent_brainonly_landings(
    landings: Iterable[BrainOnlyLanding | Mapping[str, Any]],
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    max_elapsed_seconds: float = DEFAULT_MAX_ELAPSED_SECONDS,
    max_rollback_rate: float = DEFAULT_MAX_ROLLBACK_RATE,
) -> BrainOnlyBenefitReport:
    """Review the most recent brain-only landings and flag bubble moves.

    The iterable is treated as chronological input.  Only the latest
    ``sample_size`` items are reviewed.
    """

    normalized = tuple(_normalize_landing(item) for item in landings)
    sample = normalized[-sample_size:] if sample_size > 0 else ()

    missing_evidence = tuple(
        landing.move for landing in sample if not landing.evidence
    )
    slow_moves = tuple(
        landing.move
        for landing in sample
        if landing.elapsed_seconds is None
        or landing.elapsed_seconds > max_elapsed_seconds
    )

    rolled_back_count = sum(1 for landing in sample if landing.rolled_back)
    rollback_rate = rolled_back_count / len(sample) if sample else 0.0

    elapsed_values = [
        landing.elapsed_seconds
        for landing in sample
        if landing.elapsed_seconds is not None
    ]
    average_elapsed = mean(elapsed_values) if elapsed_values else None

    bubble = set(missing_evidence)
    bubble.update(slow_moves)
    if rollback_rate > max_rollback_rate:
        bubble.update(landing.move for landing in sample if landing.rolled_back)

    reasons: list[str] = []
    if not sample:
        reasons.append("no recent brain-only landing was available for review")
    if missing_evidence:
        reasons.append("some landings lack evidence")
    if slow_moves:
        reasons.append("some landings exceeded the elapsed-time threshold")
    if rollback_rate > max_rollback_rate:
        reasons.append("rollback rate exceeded the allowed threshold")

    verdict = "keep" if sample and not bubble and not reasons else "retire_bubbles"

    return BrainOnlyBenefitReport(
        sample_size=len(sample),
        reviewed=sample,
        missing_evidence=missing_evidence,
        slow_moves=slow_moves,
        rollback_rate=rollback_rate,
        average_elapsed_seconds=average_elapsed,
        bubble_moves=tuple(sorted(bubble)),
        verdict=verdict,
        reasons=tuple(reasons),
    )


def summarize_brainonly_benefit(report: BrainOnlyBenefitReport) -> str:
    """Return a compact human-readable summary for logs or release notes."""

    avg = (
        "unknown"
        if report.average_elapsed_seconds is None
        else f"{report.average_elapsed_seconds:.1f}s"
    )
    bubbles = ", ".join(report.bubble_moves) if report.bubble_moves else "none"
    reasons = "; ".join(report.reasons) if report.reasons else "evidence holds"
    return (
        f"brain-only review: verdict={report.verdict}, "
        f"sample={report.sample_size}, rollback_rate={report.rollback_rate:.0%}, "
        f"avg_elapsed={avg}, bubble_moves={bubbles}, reasons={reasons}"
    )


def _normalize_landing(
    item: BrainOnlyLanding | Mapping[str, Any],
) -> BrainOnlyLanding:
    if isinstance(item, BrainOnlyLanding):
        return item
    return BrainOnlyLanding.from_mapping(item)


def _coerce_evidence(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        text = value.strip()
        return (text,) if text else ()
    if isinstance(value, Sequence):
        return tuple(str(part) for part in value if str(part).strip())
    return (str(value),) if str(value).strip() else ()


def _coerce_float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
