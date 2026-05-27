"""Evidence-conflict release gate.

This module is intentionally small and dependency-free so releasegate can import
it without pulling in the wider arbitration stack.

Policy:
- Evidence is grouped by capability.
- If newer evidence and older evidence for the same capability disagree on the
  capability verdict, the release must not pass silently.
- A conflict may pass only when it is explicitly arbitrated, or when the release
  context declares a downgrade/disablement for that capability.

Accepted evidence record shapes:
- dicts with keys such as capability/skill/name, verdict/status/outcome/pass,
  timestamp/created_at/ts, evidence_id/id.
- arbitrary objects exposing similarly named attributes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


_POSITIVE = {"pass", "passed", "ok", "green", "success", "succeeded", "valid", "true", "yes", "1"}
_NEGATIVE = {"fail", "failed", "bad", "red", "error", "invalid", "false", "no", "0", "regress", "regressed"}


@dataclass(frozen=True)
class EvidenceConflict:
    """A same-capability contradiction between older and newer evidence."""

    capability: str
    old_evidence_id: str
    new_evidence_id: str
    old_verdict: str
    new_verdict: str

    def to_dict(self) -> Dict[str, str]:
        return {
            "capability": self.capability,
            "old_evidence_id": self.old_evidence_id,
            "new_evidence_id": self.new_evidence_id,
            "old_verdict": self.old_verdict,
            "new_verdict": self.new_verdict,
        }


def _get(record: Any, names: Sequence[str], default: Any = None) -> Any:
    if isinstance(record, Mapping):
        for name in names:
            if name in record:
                return record[name]
        return default
    for name in names:
        if hasattr(record, name):
            return getattr(record, name)
    return default


def _capability(record: Any) -> Optional[str]:
    value = _get(record, ("capability", "skill", "ability", "feature", "name", "target"))
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _evidence_id(record: Any, fallback: int) -> str:
    value = _get(record, ("evidence_id", "id", "key", "uid", "hash"))
    if value is None:
        return "evidence-%d" % fallback
    text = str(value).strip()
    return text or ("evidence-%d" % fallback)


def _timestamp(record: Any, fallback: int) -> Tuple[int, str]:
    value = _get(record, ("timestamp", "created_at", "time", "ts", "observed_at", "sequence"))
    if value is None:
        return (0, "%012d" % fallback)
    if isinstance(value, (int, float)):
        return (1, "%020.6f" % float(value))
    return (1, str(value))


def _verdict(record: Any) -> Optional[str]:
    raw = _get(record, ("verdict", "status", "outcome", "result", "passed", "pass", "ok"))
    if raw is None:
        return None
    if isinstance(raw, bool):
        return "pass" if raw else "fail"
    text = str(raw).strip().lower()
    if not text:
        return None
    if text in _POSITIVE:
        return "pass"
    if text in _NEGATIVE:
        return "fail"
    return text


def _is_contradiction(left: str, right: str) -> bool:
    if left == right:
        return False
    return {left, right} == {"pass", "fail"}


def _normalise_names(values: Optional[Iterable[Any]]) -> Set[str]:
    result: Set[str] = set()
    if not values:
        return result
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            result.add(text)
    return result


def find_evidence_conflicts(evidence: Iterable[Any]) -> List[EvidenceConflict]:
    """Return contradictory old/new evidence pairs grouped by capability."""

    grouped: Dict[str, List[Tuple[Tuple[int, str], int, Any]]] = {}
    for index, record in enumerate(evidence or ()):
        cap = _capability(record)
        verdict = _verdict(record)
        if not cap or verdict not in {"pass", "fail"}:
            continue
        grouped.setdefault(cap, []).append((_timestamp(record, index), index, record))

    conflicts: List[EvidenceConflict] = []
    for cap, rows in grouped.items():
        rows.sort(key=lambda item: (item[0], item[1]))
        for pos in range(1, len(rows)):
            old_record = rows[pos - 1][2]
            new_record = rows[pos][2]
            old_verdict = _verdict(old_record)
            new_verdict = _verdict(new_record)
            if old_verdict and new_verdict and _is_contradiction(old_verdict, new_verdict):
                conflicts.append(
                    EvidenceConflict(
                        capability=cap,
                        old_evidence_id=_evidence_id(old_record, rows[pos - 1][1]),
                        new_evidence_id=_evidence_id(new_record, rows[pos][1]),
                        old_verdict=old_verdict,
                        new_verdict=new_verdict,
                    )
                )
    return conflicts


def evidence_conflict_releasegate(
    evidence: Iterable[Any],
    *,
    arbitrated_capabilities: Optional[Iterable[Any]] = None,
    downgraded_capabilities: Optional[Iterable[Any]] = None,
) -> Dict[str, Any]:
    """Evaluate the conflict gate.

    Returns a releasegate-style dictionary. ``allow`` is false whenever a
    same-capability evidence contradiction is neither arbitrated nor downgraded.
    """

    arbitrated = _normalise_names(arbitrated_capabilities)
    downgraded = _normalise_names(downgraded_capabilities)
    conflicts = find_evidence_conflicts(evidence)
    blocking = [
        conflict
        for conflict in conflicts
        if conflict.capability not in arbitrated and conflict.capability not in downgraded
    ]

    return {
        "gate": "evidence_conflict",
        "allow": not blocking,
        "status": "pass" if not blocking else "block",
        "reason": (
            "no unresolved evidence conflicts"
            if not blocking
            else "unresolved contradictory evidence must be arbitrated or downgraded before release"
        ),
        "conflicts": [conflict.to_dict() for conflict in conflicts],
        "blocking_conflicts": [conflict.to_dict() for conflict in blocking],
        "arbitrated_capabilities": sorted(arbitrated),
        "downgraded_capabilities": sorted(downgraded),
    }


def releasegate_check(context: Any) -> Dict[str, Any]:
    """Releasegate hook accepting a loose context mapping/object."""

    evidence = _get(context, ("evidence", "evidence_records", "records"), ())
    arbitrated = _get(context, ("arbitrated_capabilities", "arbitrated", "conflict_arbitrated"), ())
    downgraded = _get(context, ("downgraded_capabilities", "downgraded", "degraded", "disabled_capabilities"), ())
    return evidence_conflict_releasegate(
        evidence,
        arbitrated_capabilities=arbitrated,
        downgraded_capabilities=downgraded,
    )


def build_releasegate_check() -> Any:
    """Return a callable suitable for releasegate registries."""

    return releasegate_check


check = releasegate_check
gate = evidence_conflict_releasegate

__all__ = [
    "EvidenceConflict",
    "build_releasegate_check",
    "check",
    "evidence_conflict_releasegate",
    "find_evidence_conflicts",
    "gate",
    "releasegate_check",
]
