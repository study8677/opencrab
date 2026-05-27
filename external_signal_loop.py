"""Trace external signals into verifiable evolution requirements.

This module is intentionally dependency-light: it gives the long-hand path
``intake -> value -> planner -> evidence`` a single auditable envelope so an
outside signal can be shown as heard, valued, planned, and evidenced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from time import time
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


_STAGE_ORDER = ("intake", "value", "planner", "evidence")


def _stable_digest(parts: Iterable[Any], length: int = 12) -> str:
    text = "\n".join(str(part) for part in parts if part is not None)
    return sha256(text.encode("utf-8")).hexdigest()[:length]


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


@dataclass(frozen=True)
class StageRecord:
    """One auditable step in the external-signal loop."""

    stage: str
    status: str
    summary: str
    data: Mapping[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "stage": self.stage,
            "status": self.status,
            "summary": self.summary,
            "data": dict(self.data),
            "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class TraceableRequirement:
    """A requirement that preserves its path from signal to evidence."""

    requirement_id: str
    signal_id: str
    title: str
    requirement: str
    acceptance: Sequence[str]
    stages: Sequence[StageRecord]
    evidence: Sequence[str]

    def stage_names(self) -> List[str]:
        return [stage.stage for stage in self.stages]

    def is_closed_loop(self) -> bool:
        return self.stage_names() == list(_STAGE_ORDER) and bool(self.evidence)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "requirement_id": self.requirement_id,
            "signal_id": self.signal_id,
            "title": self.title,
            "requirement": self.requirement,
            "acceptance": list(self.acceptance),
            "stages": [stage.as_dict() for stage in self.stages],
            "evidence": list(self.evidence),
            "closed_loop": self.is_closed_loop(),
        }


def intake_external_signal(
    signal: Any,
    *,
    source: str = "external",
    user_need: Optional[str] = None,
) -> StageRecord:
    """Normalize an outside signal into a stable intake record."""

    text = _clean_text(signal)
    if not text:
        raise ValueError("external signal must not be empty")

    signal_id = "sig-" + _stable_digest((source, text))
    summary = text[:160]
    return StageRecord(
        stage="intake",
        status="heard",
        summary=summary,
        data={
            "signal_id": signal_id,
            "source": _clean_text(source) or "external",
            "raw_signal": text,
            "user_need": _clean_text(user_need) or summary,
        },
    )


def score_signal_value(intake: StageRecord) -> StageRecord:
    """Convert intake into a compact value statement."""

    if intake.stage != "intake":
        raise ValueError("score_signal_value expects an intake stage")

    raw_signal = str(intake.data.get("raw_signal", intake.summary))
    user_need = str(intake.data.get("user_need", intake.summary))
    tokens = {token.strip(".,;:!?()[]{}").lower() for token in raw_signal.split()}
    specificity = min(1.0, len([token for token in tokens if len(token) >= 5]) / 12.0)
    closure_bonus = 0.25 if any(
        word in tokens for word in {"evidence", "验收", "闭环", "traceable", "proof"}
    ) else 0.0
    score = round(min(1.0, 0.45 + specificity + closure_bonus), 2)

    return StageRecord(
        stage="value",
        status="valued",
        summary=f"External need: {user_need}",
        data={
            "signal_id": intake.data["signal_id"],
            "value_score": score,
            "why": "Shows that an outside signal can become a concrete evolution requirement.",
            "user_need": user_need,
        },
    )


def plan_traceable_requirement(
    intake: StageRecord,
    value: StageRecord,
    *,
    title: Optional[str] = None,
) -> StageRecord:
    """Plan the valued signal as an acceptance-testable requirement."""

    if intake.stage != "intake" or value.stage != "value":
        raise ValueError("plan_traceable_requirement expects intake and value stages")

    signal_id = str(intake.data["signal_id"])
    raw_signal = str(intake.data.get("raw_signal", intake.summary))
    requirement_id = "req-" + _stable_digest((signal_id, raw_signal, value.summary))
    chosen_title = _clean_text(title) or "External signal closed-loop acceptance"

    acceptance = [
        "intake records the outside signal with a stable signal_id",
        "value records why the signal matters and assigns a value_score",
        "planner emits a requirement_id linked to the signal_id",
        "evidence records artifacts proving the requirement was followed",
    ]

    return StageRecord(
        stage="planner",
        status="planned",
        summary=chosen_title,
        data={
            "signal_id": signal_id,
            "requirement_id": requirement_id,
            "requirement": (
                "Run the external signal through intake->value->planner->evidence "
                "and keep every handoff traceable."
            ),
            "acceptance": acceptance,
            "planned_actions": [
                "normalize external signal",
                "score value and user need",
                "create traceable requirement",
                "attach evidence artifacts",
            ],
        },
    )


def collect_loop_evidence(
    intake: StageRecord,
    value: StageRecord,
    plan: StageRecord,
    *,
    artifacts: Optional[Sequence[str]] = None,
) -> StageRecord:
    """Attach evidence proving the closed loop happened."""

    if plan.stage != "planner":
        raise ValueError("collect_loop_evidence expects a planner stage")

    artifact_list = [
        _clean_text(item)
        for item in (artifacts or ())
        if _clean_text(item)
    ]
    if not artifact_list:
        artifact_list = [
            f"signal:{intake.data['signal_id']}",
            f"value_score:{value.data['value_score']}",
            f"requirement:{plan.data['requirement_id']}",
        ]

    return StageRecord(
        stage="evidence",
        status="verified",
        summary="Closed-loop trace contains intake, value, planner, and evidence.",
        data={
            "signal_id": intake.data["signal_id"],
            "requirement_id": plan.data["requirement_id"],
            "artifacts": artifact_list,
            "stage_order": list(_STAGE_ORDER),
        },
    )


def run_external_signal_loop(
    signal: Any,
    *,
    source: str = "external",
    user_need: Optional[str] = None,
    title: Optional[str] = None,
    artifacts: Optional[Sequence[str]] = None,
) -> TraceableRequirement:
    """Run intake -> value -> planner -> evidence for one outside signal."""

    intake = intake_external_signal(signal, source=source, user_need=user_need)
    value = score_signal_value(intake)
    plan = plan_traceable_requirement(intake, value, title=title)
    evidence = collect_loop_evidence(intake, value, plan, artifacts=artifacts)

    return TraceableRequirement(
        requirement_id=str(plan.data["requirement_id"]),
        signal_id=str(intake.data["signal_id"]),
        title=str(plan.summary),
        requirement=str(plan.data["requirement"]),
        acceptance=list(plan.data["acceptance"]),
        stages=[intake, value, plan, evidence],
        evidence=list(evidence.data["artifacts"]),
    )


def verify_external_signal_loop(requirement: TraceableRequirement) -> Dict[str, Any]:
    """Return a small acceptance report for the traceable requirement."""

    stage_names = requirement.stage_names()
    missing = [stage for stage in _STAGE_ORDER if stage not in stage_names]
    ordered = stage_names == list(_STAGE_ORDER)
    linked = all(
        getattr(stage, "data", {}).get("signal_id") == requirement.signal_id
        for stage in requirement.stages
    )
    passed = ordered and linked and not missing and bool(requirement.evidence)

    return {
        "passed": passed,
        "requirement_id": requirement.requirement_id,
        "signal_id": requirement.signal_id,
        "ordered": ordered,
        "linked": linked,
        "missing": missing,
        "evidence_count": len(requirement.evidence),
    }


__all__ = [
    "StageRecord",
    "TraceableRequirement",
    "collect_loop_evidence",
    "intake_external_signal",
    "plan_traceable_requirement",
    "run_external_signal_loop",
    "score_signal_value",
    "verify_external_signal_loop",
]
