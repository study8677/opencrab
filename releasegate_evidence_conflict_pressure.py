"""Pressure regression for conflicting evidence, trustscore, and release gate signals.

The goal is deliberately conservative: if the three signals disagree in ways that
could make a release look green while carrying contradictory evidence, the gate
must halt and explain which arbitration rule stopped it.
"""

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple


@dataclass(frozen=True)
class EvidenceItem:
    name: str
    claim: str
    severity: str = "medium"


@dataclass(frozen=True)
class ConflictSample:
    case_id: str
    evidence: Tuple[EvidenceItem, ...]
    trustscore: float
    releasegate: str


@dataclass(frozen=True)
class GateVerdict:
    case_id: str
    decision: str
    reasons: Tuple[str, ...]


TRUST_THRESHOLD = 0.75
GREEN_STATES = {"green", "approve", "approved", "pass"}


def pressure_samples() -> Tuple[ConflictSample, ...]:
    """Return three intentionally contradictory release-gate samples."""

    return (
        ConflictSample(
            case_id="high_trust_but_evidence_split",
            evidence=(
                EvidenceItem("unit-suite", "pass", "low"),
                EvidenceItem("canary-replay", "fail", "high"),
                EvidenceItem("operator-note", "pass", "medium"),
            ),
            trustscore=0.93,
            releasegate="green",
        ),
        ConflictSample(
            case_id="gate_green_but_trustscore_red",
            evidence=(
                EvidenceItem("freshness-check", "pass", "low"),
                EvidenceItem("coverage-delta", "weak", "medium"),
                EvidenceItem("risk-review", "pass", "low"),
            ),
            trustscore=0.41,
            releasegate="approved",
        ),
        ConflictSample(
            case_id="green_release_against_blocking_evidence",
            evidence=(
                EvidenceItem("security-scan", "block", "critical"),
                EvidenceItem("rollback-drill", "pass", "medium"),
                EvidenceItem("maintainer-override", "pass", "medium"),
            ),
            trustscore=0.88,
            releasegate="pass",
        ),
    )


def _claims(evidence: Iterable[EvidenceItem]) -> List[str]:
    return [item.claim.strip().lower() for item in evidence]


def _has_blocking_evidence(evidence: Sequence[EvidenceItem]) -> bool:
    blocking_claims = {"block", "fail", "failed", "rollback", "regress", "regression"}
    return any(
        item.claim.strip().lower() in blocking_claims
        or item.severity.strip().lower() == "critical"
        for item in evidence
    )


def arbitrate_release(sample: ConflictSample) -> GateVerdict:
    """Apply stop-first arbitration to a conflicted release sample."""

    reasons: List[str] = []
    claims = set(_claims(sample.evidence))
    gate_is_green = sample.releasegate.strip().lower() in GREEN_STATES

    if "pass" in claims and ("fail" in claims or "failed" in claims):
        reasons.append("evidence_conflict: pass and fail evidence both present")

    if sample.trustscore < TRUST_THRESHOLD and gate_is_green:
        reasons.append(
            "trustscore_releasegate_conflict: green gate below trust threshold"
        )

    if _has_blocking_evidence(sample.evidence) and gate_is_green:
        reasons.append("blocking_evidence_conflict: green gate has blocking evidence")

    if reasons:
        return GateVerdict(sample.case_id, "halt", tuple(reasons))

    return GateVerdict(sample.case_id, "allow", ("no conflict detected",))


def run_pressure_regression() -> Tuple[GateVerdict, ...]:
    verdicts = tuple(arbitrate_release(sample) for sample in pressure_samples())

    if len(verdicts) != 3:
        raise AssertionError("expected exactly three conflict pressure samples")

    escaped = [verdict for verdict in verdicts if verdict.decision != "halt"]
    if escaped:
        names = ", ".join(verdict.case_id for verdict in escaped)
        raise AssertionError(f"release gate failed to halt conflicted samples: {names}")

    missing_reasons = [verdict.case_id for verdict in verdicts if not verdict.reasons]
    if missing_reasons:
        names = ", ".join(missing_reasons)
        raise AssertionError(f"halted samples lacked arbitration reasons: {names}")

    return verdicts


def test_releasegate_halts_on_three_conflict_samples() -> None:
    run_pressure_regression()


if __name__ == "__main__":
    for result in run_pressure_regression():
        print(f"{result.case_id}: {result.decision} - {'; '.join(result.reasons)}")
