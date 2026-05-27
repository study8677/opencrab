"""Branchlab -> canary -> releasegate self-release rehearsal.

This module is intentionally small and dependency-light.  It lets the hand
practice a safe rollout loop for a real low-risk patch:

1. open an isolated branch-lab trial,
2. send only a tiny canary slice,
3. decide at a release gate using explicit evidence,
4. prepare rollback instructions before widening traffic.

The functions here do not mutate the repository.  They produce a structured
plan that other tools can persist, inspect, or execute.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping


@dataclass(frozen=True)
class DrillSignal:
    """One measurable rollout signal."""

    name: str
    value: float
    limit: float
    direction: str = "max"
    note: str = ""

    def passed(self) -> bool:
        """Return whether this signal is within its allowed bound."""
        if self.direction == "max":
            return self.value <= self.limit
        if self.direction == "min":
            return self.value >= self.limit
        raise ValueError(f"unsupported signal direction: {self.direction!r}")

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "value": self.value,
            "limit": self.limit,
            "direction": self.direction,
            "passed": self.passed(),
            "note": self.note,
        }


@dataclass(frozen=True)
class RolloutDecision:
    """The releasegate verdict for a canary drill."""

    verdict: str
    reason: str
    next_traffic_percent: float
    rollback_required: bool
    evidence: tuple[DrillSignal, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "reason": self.reason,
            "next_traffic_percent": self.next_traffic_percent,
            "rollback_required": self.rollback_required,
            "evidence": [signal.as_dict() for signal in self.evidence],
        }


@dataclass(frozen=True)
class ReleaseDrillPlan:
    """A complete branchlab -> canary -> releasegate rehearsal artifact."""

    patch_id: str
    branch_name: str
    canary_percent: float
    decision: RolloutDecision
    rollback_steps: tuple[str, ...]
    created_at: str

    def as_dict(self) -> dict[str, object]:
        return {
            "patch_id": self.patch_id,
            "branch_name": self.branch_name,
            "canary_percent": self.canary_percent,
            "decision": self.decision.as_dict(),
            "rollback_steps": list(self.rollback_steps),
            "created_at": self.created_at,
        }


def default_low_risk_signals(metrics: Mapping[str, float] | None = None) -> tuple[DrillSignal, ...]:
    """Build conservative signals for a tiny canary.

    Accepted metric keys:
    - error_rate: maximum 1%
    - p95_latency_ms: maximum 500ms
    - rollback_seconds: maximum 120s
    - smoke_pass_rate: minimum 100%
    """

    values = dict(metrics or {})
    return (
        DrillSignal("error_rate", float(values.get("error_rate", 0.0)), 0.01, "max"),
        DrillSignal("p95_latency_ms", float(values.get("p95_latency_ms", 0.0)), 500.0, "max"),
        DrillSignal("rollback_seconds", float(values.get("rollback_seconds", 0.0)), 120.0, "max"),
        DrillSignal("smoke_pass_rate", float(values.get("smoke_pass_rate", 1.0)), 1.0, "min"),
    )


def injected_failure_signals(
    case: str,
    metrics: Mapping[str, float] | None = None,
) -> tuple[DrillSignal, ...]:
    """Return canary signals with one deliberate releasegate failure injected.
    
    Supported cases:
    - evidence_expired: stale evidence must block widening.
    - key_false_positive: an untriaged secret-scan alert, even if later false,
      must block release until explicitly cleared.
    - rollback_failed: failed rollback verification must block release.
    """
    
    normalized = case.strip().lower().replace("-", "_")
    signals = list(default_low_risk_signals(metrics))
    
    if normalized == "evidence_expired":
        signals.append(
            DrillSignal(
                "evidence_age_seconds",
                7200.0,
                900.0,
                "max",
                "injected stale release evidence; gate must demand fresh proof",
            )
        )
    elif normalized == "key_false_positive":
        signals.append(
            DrillSignal(
                "untriaged_secret_alerts",
                1.0,
                0.0,
                "max",
                "injected key false-positive alert; gate must wait for triage",
            )
        )
    elif normalized == "rollback_failed":
        signals.append(
            DrillSignal(
                "rollback_verified",
                0.0,
                1.0,
                "min",
                "injected rollback failure; gate must not widen without recovery",
            )
        )
    else:
        raise ValueError(f"unsupported release drill failure injection: {case!r}")
    
    return tuple(signals)


def run_failure_injection_drills(
    canary_percent: float = 1.0,
) -> dict[str, RolloutDecision]:
    """Exercise the releasegate against the three required bad-shell cases."""
    
    cases = ("evidence_expired", "key_false_positive", "rollback_failed")
    return {
        case: decide_releasegate(injected_failure_signals(case), canary_percent=canary_percent)
        for case in cases
    }


def decide_releasegate(
    signals: Iterable[DrillSignal],
    canary_percent: float = 1.0,
    widen_to_percent: float = 10.0,
) -> RolloutDecision:
    """Decide whether the canary may widen or must roll back."""

    evidence = tuple(signals)
    failed = [signal for signal in evidence if not signal.passed()]

    if canary_percent <= 0 or canary_percent > 5:
        return RolloutDecision(
            verdict="hold",
            reason="canary percent must stay in the low-risk 0-5 range",
            next_traffic_percent=0.0,
            rollback_required=True,
            evidence=evidence,
        )

    if failed:
        names = ", ".join(signal.name for signal in failed)
        return RolloutDecision(
            verdict="rollback",
            reason=f"releasegate failed signals: {names}",
            next_traffic_percent=0.0,
            rollback_required=True,
            evidence=evidence,
        )

    return RolloutDecision(
        verdict="widen",
        reason="all branchlab and canary signals passed",
        next_traffic_percent=widen_to_percent,
        rollback_required=False,
        evidence=evidence,
    )


def build_release_drill_plan(
    patch_id: str,
    metrics: Mapping[str, float] | None = None,
    canary_percent: float = 1.0,
) -> ReleaseDrillPlan:
    """Create a safe rollout rehearsal plan for a low-risk patch."""

    clean_patch_id = patch_id.strip() or "unknown-patch"
    branch_name = "branchlab/" + clean_patch_id.replace(" ", "-")
    signals = default_low_risk_signals(metrics)
    decision = decide_releasegate(signals, canary_percent=canary_percent)

    rollback_steps = (
        "freeze further traffic widening",
        f"route canary traffic for {clean_patch_id} back to baseline",
        f"revert or disable branch {branch_name}",
        "rerun smoke checks and record releasegate evidence",
    )

    return ReleaseDrillPlan(
        patch_id=clean_patch_id,
        branch_name=branch_name,
        canary_percent=canary_percent,
        decision=decision,
        rollback_steps=rollback_steps,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


__all__ = [
    "DrillSignal",
    "ReleaseDrillPlan",
    "RolloutDecision",
    "build_release_drill_plan",
    "decide_releasegate",
    "default_low_risk_signals",
    "injected_failure_signals",
    "run_failure_injection_drills",
]
