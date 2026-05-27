"""Evidence-conflict downgrade drill.

This module rehearses a conservative autonomy path:

1. fabricate mutually exclusive evidence,
2. arbitrate the conflict,
3. feed the arbitration result into a release gate,
4. produce a rollback plan when the gate refuses release.

The point of the drill is not to "win" the gate.  The successful outcome is a
controlled stop with a concrete rollback path, because stopping on contradictory
evidence is safer than forcing a release through a conflicted evidence set.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Dict, Iterable, List, Sequence


@dataclass(frozen=True)
class DrillEvidence:
    """A small evidence record used by the downgrade drill."""

    evidence_id: str
    claim: str
    polarity: str
    confidence: float
    source: str
    note: str

    def normalized_polarity(self) -> str:
        value = self.polarity.strip().lower()
        if value in {"support", "supports", "positive", "pass", "true"}:
            return "support"
        if value in {"oppose", "opposes", "negative", "fail", "false"}:
            return "oppose"
        return "unknown"


@dataclass(frozen=True)
class ArbitrationDecision:
    """Outcome of conflict arbitration."""

    status: str
    action: str
    reason: str
    conflicting_claims: List[str]
    evidence_ids: List[str]


@dataclass(frozen=True)
class ReleaseGateDecision:
    """Release gate result after arbitration."""

    allowed: bool
    level: str
    reason: str


@dataclass(frozen=True)
class RollbackPlan:
    """Rollback instructions emitted when release is blocked."""

    required: bool
    reason: str
    steps: List[str]


@dataclass(frozen=True)
class DrillResult:
    """Full arbitration -> releasegate -> rollback rehearsal result."""

    evidence: List[DrillEvidence]
    arbitration: ArbitrationDecision
    releasegate: ReleaseGateDecision
    rollback: RollbackPlan

    def to_dict(self) -> Dict[str, object]:
        return asdict(self)


def fabricate_mutually_exclusive_evidence() -> List[DrillEvidence]:
    """Create a minimal pair of mutually exclusive evidence records."""

    claim = "candidate_patch_preserves_user_visible_behavior"
    return [
        DrillEvidence(
            evidence_id="conflict-support-001",
            claim=claim,
            polarity="support",
            confidence=0.84,
            source="synthetic-green-regression",
            note="Regression sample reports no behavior drift.",
        ),
        DrillEvidence(
            evidence_id="conflict-oppose-001",
            claim=claim,
            polarity="oppose",
            confidence=0.81,
            source="synthetic-red-counterexample",
            note="Counterexample reports behavior drift on the same claim.",
        ),
    ]


def arbitrate_conflict(evidence: Sequence[DrillEvidence]) -> ArbitrationDecision:
    """Detect mutually exclusive evidence and choose a conservative downgrade."""

    by_claim: Dict[str, Dict[str, List[DrillEvidence]]] = {}
    for item in evidence:
        by_claim.setdefault(item.claim, {}).setdefault(item.normalized_polarity(), []).append(item)

    conflicting_claims = [
        claim
        for claim, polarities in by_claim.items()
        if polarities.get("support") and polarities.get("oppose")
    ]

    if conflicting_claims:
        conflict_ids = [
            item.evidence_id
            for item in evidence
            if item.claim in conflicting_claims
        ]
        return ArbitrationDecision(
            status="conflict",
            action="downgrade_to_manual_stop",
            reason="Mutually exclusive evidence exists for the same release claim.",
            conflicting_claims=conflicting_claims,
            evidence_ids=conflict_ids,
        )

    return ArbitrationDecision(
        status="clear",
        action="continue",
        reason="No same-claim support/oppose evidence conflict was found.",
        conflicting_claims=[],
        evidence_ids=[item.evidence_id for item in evidence],
    )


def release_gate(arbitration: ArbitrationDecision) -> ReleaseGateDecision:
    """Block release when arbitration found conflict."""

    if arbitration.status == "conflict":
        return ReleaseGateDecision(
            allowed=False,
            level="blocked",
            reason="Release gate refuses conflicted evidence; stop is safer than hard pass.",
        )

    return ReleaseGateDecision(
        allowed=True,
        level="open",
        reason="Arbitration found no evidence conflict.",
    )


def rollback_after_gate(gate: ReleaseGateDecision) -> RollbackPlan:
    """Return a rollback plan for blocked releases."""

    if gate.allowed:
        return RollbackPlan(
            required=False,
            reason="Release gate allowed the change; rollback rehearsal remains idle.",
            steps=[],
        )

    return RollbackPlan(
        required=True,
        reason="Release blocked by evidence conflict downgrade.",
        steps=[
            "freeze_candidate_patch",
            "preserve_conflicting_evidence_bundle",
            "restore_last_known_good_state",
            "request_fresh_independent_evidence_before_retry",
        ],
    )


def run_drill(evidence: Iterable[DrillEvidence] | None = None) -> DrillResult:
    """Run the complete downgrade drill."""

    evidence_list = list(evidence) if evidence is not None else fabricate_mutually_exclusive_evidence()
    arbitration = arbitrate_conflict(evidence_list)
    gate = release_gate(arbitration)
    rollback = rollback_after_gate(gate)
    return DrillResult(
        evidence=evidence_list,
        arbitration=arbitration,
        releasegate=gate,
        rollback=rollback,
    )


def main() -> int:
    """CLI entry point for manual rehearsal."""

    result = run_drill()
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result.rollback.required and not result.releasegate.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
