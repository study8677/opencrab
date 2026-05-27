"""Release-gate evidence conflict arbitration.

This module protects signing/release issuance when evidence disagrees.
The critical regression covered here is:

    expired success evidence + fresh failure evidence => DO NOT ISSUE

A stale success must never outvote a fresh failure.  Callers may use
``releasegate_allows``/``should_issue_release`` before producing any signed
release artifact, or ``issue_release_certificate`` when they want a tiny
in-process certificate object.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import time
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple


DEFAULT_MAX_AGE_SECONDS = 24 * 60 * 60


@dataclass(frozen=True)
class EvidenceItem:
    """Normalized evidence used by the conflict-aware release gate."""

    name: str
    passed: bool
    observed_at: float
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS
    detail: str = ""

    @property
    def expires_at(self) -> float:
        return self.observed_at + self.max_age_seconds

    def is_fresh(self, now: Optional[float] = None) -> bool:
        if now is None:
            now = time()
        return self.expires_at >= now


@dataclass(frozen=True)
class EvidenceConflictDecision:
    """Arbitration result for release-gate evidence."""

    allowed: bool
    reason: str
    fresh_failures: Tuple[EvidenceItem, ...] = ()
    stale_successes: Tuple[EvidenceItem, ...] = ()
    stale_failures: Tuple[EvidenceItem, ...] = ()
    fresh_successes: Tuple[EvidenceItem, ...] = ()

    @property
    def blocked(self) -> bool:
        return not self.allowed


def _read_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "pass", "passed", "ok", "success"}
    return bool(value)


def _read_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def normalize_evidence(item: Any, *, default_name: str = "evidence") -> EvidenceItem:
    """Convert common evidence shapes into :class:`EvidenceItem`.

    Accepted inputs:
    - EvidenceItem
    - mapping with keys such as name/check/id, passed/ok/success, observed_at/ts/timestamp,
      max_age_seconds/ttl/fresh_for, detail/reason/message
    - object with similarly named attributes
    """

    if isinstance(item, EvidenceItem):
        return item

    if isinstance(item, Mapping):
        get = item.get
    else:
        get = lambda key, default=None: getattr(item, key, default)

    name = str(get("name", get("check", get("id", default_name))))
    passed = _read_bool(get("passed", get("ok", get("success", False))))
    observed_at = _read_float(get("observed_at", get("ts", get("timestamp", 0.0))), 0.0)
    max_age = _read_float(
        get("max_age_seconds", get("ttl", get("fresh_for", DEFAULT_MAX_AGE_SECONDS))),
        DEFAULT_MAX_AGE_SECONDS,
    )
    detail = str(get("detail", get("reason", get("message", ""))))
    return EvidenceItem(
        name=name,
        passed=passed,
        observed_at=observed_at,
        max_age_seconds=max_age,
        detail=detail,
    )


def arbitrate_evidence_conflict(
    evidence: Iterable[Any],
    *,
    now: Optional[float] = None,
) -> EvidenceConflictDecision:
    """Arbitrate release evidence before signing.

    Safety rule:
    - Any fresh failure blocks release.
    - Stale successes are ignored for permission and recorded as conflict context.
    - At least one fresh success is required when no fresh failure exists.
    """

    if now is None:
        now = time()

    fresh_failures = []
    stale_successes = []
    stale_failures = []
    fresh_successes = []

    for index, raw in enumerate(evidence):
        item = normalize_evidence(raw, default_name=f"evidence:{index}")
        fresh = item.is_fresh(now)
        if item.passed and fresh:
            fresh_successes.append(item)
        elif item.passed and not fresh:
            stale_successes.append(item)
        elif not item.passed and fresh:
            fresh_failures.append(item)
        else:
            stale_failures.append(item)

    if fresh_failures:
        names = ", ".join(item.name for item in fresh_failures)
        stale = ", ".join(item.name for item in stale_successes) or "none"
        return EvidenceConflictDecision(
            allowed=False,
            reason=f"blocked: fresh failure evidence wins over stale success evidence; failures={names}; stale_successes={stale}",
            fresh_failures=tuple(fresh_failures),
            stale_successes=tuple(stale_successes),
            stale_failures=tuple(stale_failures),
            fresh_successes=tuple(fresh_successes),
        )

    if not fresh_successes:
        return EvidenceConflictDecision(
            allowed=False,
            reason="blocked: no fresh successful evidence available for release signing",
            fresh_failures=tuple(fresh_failures),
            stale_successes=tuple(stale_successes),
            stale_failures=tuple(stale_failures),
            fresh_successes=tuple(fresh_successes),
        )

    return EvidenceConflictDecision(
        allowed=True,
        reason="allowed: fresh success evidence present and no fresh failures",
        fresh_failures=tuple(fresh_failures),
        stale_successes=tuple(stale_successes),
        stale_failures=tuple(stale_failures),
        fresh_successes=tuple(fresh_successes),
    )


def releasegate_allows(evidence: Iterable[Any], *, now: Optional[float] = None) -> bool:
    """Boolean release gate used by simple callers."""

    return arbitrate_evidence_conflict(evidence, now=now).allowed


def should_issue_release(evidence: Iterable[Any], *, now: Optional[float] = None) -> bool:
    """Compatibility alias for callers phrased around issuance."""

    return releasegate_allows(evidence, now=now)


def issue_release_certificate(
    evidence: Iterable[Any],
    *,
    now: Optional[float] = None,
    subject: str = "release",
) -> Mapping[str, Any]:
    """Return a small unsigned certificate only when the conflict gate allows it.

    The function deliberately raises on blocked arbitration so callers cannot
    accidentally continue with a partially issued release artifact.
    """

    if now is None:
        now = time()
    decision = arbitrate_evidence_conflict(evidence, now=now)
    if not decision.allowed:
        raise PermissionError(decision.reason)
    return {
        "subject": subject,
        "issued_at": now,
        "allowed": True,
        "reason": decision.reason,
        "fresh_successes": [item.name for item in decision.fresh_successes],
    }


def expired_success_fresh_failure_fixture(now: float = 1_700_000_000.0) -> Sequence[EvidenceItem]:
    """Fixture for the release-gate conflict that previously risked mis-issuance."""

    return (
        EvidenceItem(
            name="old-green-ci",
            passed=True,
            observed_at=now - (2 * DEFAULT_MAX_AGE_SECONDS),
            max_age_seconds=DEFAULT_MAX_AGE_SECONDS,
            detail="expired success must not authorize signing",
        ),
        EvidenceItem(
            name="fresh-red-canary",
            passed=False,
            observed_at=now - 60,
            max_age_seconds=DEFAULT_MAX_AGE_SECONDS,
            detail="fresh failure must block signing",
        ),
    )


def regression_expired_success_fresh_failure_blocks() -> bool:
    """Executable regression: stale pass + fresh fail must block release."""

    now = 1_700_000_000.0
    evidence = expired_success_fresh_failure_fixture(now)
    decision = arbitrate_evidence_conflict(evidence, now=now)
    if decision.allowed:
        raise AssertionError("release gate mis-issued: expired success overrode fresh failure")
    if not decision.fresh_failures:
        raise AssertionError("regression fixture did not produce a fresh failure")
    if not decision.stale_successes:
        raise AssertionError("regression fixture did not produce a stale success")
    try:
        issue_release_certificate(evidence, now=now)
    except PermissionError:
        return True
    raise AssertionError("certificate was issued despite conflicting fresh failure")


if __name__ == "__main__":
    regression_expired_success_fresh_failure_blocks()
    print("ok: expired success + fresh failure blocks release signing")
