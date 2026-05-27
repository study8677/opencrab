"""Skill decay rehearsal utilities.

This module keeps critical, high-heat abilities fresh by selecting stale
capabilities, injecting lightweight dependency/field-drift drills, running a
minimal validation predicate, and producing a refresh order.

It is intentionally self-contained: no network, no third-party imports, and no
assumptions about the surrounding storage format.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_time(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    return None


def _age_days(value: Any, *, at: Optional[datetime] = None) -> float:
    seen = _parse_time(value)
    if seen is None:
        return 10_000.0
    current = at or _now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return max(0.0, (current - seen).total_seconds() / 86_400.0)


@dataclass(frozen=True)
class SkillCandidate:
    """A capability that may need freshness rehearsal."""

    name: str
    heat: float = 0.0
    last_verified: Any = None
    dependencies: Tuple[str, ...] = ()
    fields: Tuple[str, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "SkillCandidate":
        name = str(raw.get("name") or raw.get("skill") or raw.get("id") or "unnamed")
        dependencies = raw.get("dependencies", raw.get("deps", ()))
        fields = raw.get("fields", raw.get("schema", ()))
        if isinstance(dependencies, str):
            dependencies = (dependencies,)
        if isinstance(fields, str):
            fields = (fields,)
        return cls(
            name=name,
            heat=float(raw.get("heat", raw.get("usage_heat", 0.0)) or 0.0),
            last_verified=raw.get("last_verified", raw.get("verified_at")),
            dependencies=tuple(str(item) for item in dependencies or ()),
            fields=tuple(str(item) for item in fields or ()),
            metadata=dict(raw),
        )

    def stale_days(self, *, at: Optional[datetime] = None) -> float:
        return _age_days(self.last_verified, at=at)


@dataclass(frozen=True)
class DrillFault:
    """A small synthetic fault used to test whether the skill still survives."""

    kind: str
    target: str
    detail: str


@dataclass(frozen=True)
class DrillResult:
    """Outcome of one skill decay rehearsal."""

    skill: str
    score: float
    stale_days: float
    faults: Tuple[DrillFault, ...]
    passed: bool
    evidence: Mapping[str, Any] = field(default_factory=dict)


def rank_stale_hot_skills(
    skills: Iterable[Mapping[str, Any] | SkillCandidate],
    *,
    limit: int = 5,
    min_heat: float = 0.0,
    at: Optional[datetime] = None,
) -> List[SkillCandidate]:
    """Return high-heat, stale skills sorted by refresh urgency."""

    candidates: List[SkillCandidate] = []
    for item in skills:
        candidate = item if isinstance(item, SkillCandidate) else SkillCandidate.from_mapping(item)
        if candidate.heat >= min_heat:
            candidates.append(candidate)

    candidates.sort(
        key=lambda skill: (
            skill.heat * max(1.0, skill.stale_days(at=at)),
            skill.heat,
            skill.stale_days(at=at),
            skill.name,
        ),
        reverse=True,
    )
    return candidates[: max(0, int(limit))]


def build_decay_faults(skill: SkillCandidate) -> Tuple[DrillFault, ...]:
    """Create dependency-outage and field-drift faults for a skill."""

    faults: List[DrillFault] = []
    if skill.dependencies:
        faults.append(
            DrillFault(
                kind="dependency_outage",
                target=skill.dependencies[0],
                detail="simulate unavailable dependency and require local fallback",
            )
        )
    else:
        faults.append(
            DrillFault(
                kind="dependency_outage",
                target="implicit_external_context",
                detail="simulate missing external context and require graceful degradation",
            )
        )

    if skill.fields:
        faults.append(
            DrillFault(
                kind="field_drift",
                target=skill.fields[0],
                detail="simulate renamed/missing field and require tolerant parsing",
            )
        )
    else:
        faults.append(
            DrillFault(
                kind="field_drift",
                target="implicit_payload_shape",
                detail="simulate extra and missing payload fields",
            )
        )

    return tuple(faults)


def default_minimal_verify(skill: SkillCandidate, faults: Sequence[DrillFault]) -> Tuple[bool, Dict[str, Any]]:
    """Conservative built-in verifier for dry-run rehearsals.

    A real caller may pass a stronger verifier.  The default checks only that
    the drill has a named skill and covers both intended fault classes.
    """

    kinds = {fault.kind for fault in faults}
    passed = bool(skill.name) and {"dependency_outage", "field_drift"}.issubset(kinds)
    return passed, {
        "verifier": "default_minimal_verify",
        "covered_faults": sorted(kinds),
        "dependency_count": len(skill.dependencies),
        "field_count": len(skill.fields),
    }


def run_skill_decay_drill(
    skills: Iterable[Mapping[str, Any] | SkillCandidate],
    *,
    limit: int = 5,
    min_heat: float = 0.0,
    verifier: Optional[
        Callable[[SkillCandidate, Sequence[DrillFault]], bool | Tuple[bool, Mapping[str, Any]]]
    ] = None,
    at: Optional[datetime] = None,
) -> List[DrillResult]:
    """Run a minimal freshness drill and return results in refresh order."""

    verify = verifier or default_minimal_verify
    results: List[DrillResult] = []

    for skill in rank_stale_hot_skills(skills, limit=limit, min_heat=min_heat, at=at):
        faults = build_decay_faults(skill)
        raw = verify(skill, faults)
        if isinstance(raw, tuple):
            passed = bool(raw[0])
            evidence = dict(raw[1]) if len(raw) > 1 and isinstance(raw[1], Mapping) else {}
        else:
            passed = bool(raw)
            evidence = {}

        stale = skill.stale_days(at=at)
        score = skill.heat * max(1.0, stale)
        if not passed:
            score *= 1.5

        results.append(
            DrillResult(
                skill=skill.name,
                score=score,
                stale_days=stale,
                faults=faults,
                passed=passed,
                evidence=evidence,
            )
        )

    results.sort(key=lambda item: (not item.passed, item.score, item.stale_days, item.skill), reverse=True)
    return results


def freshness_queue(results: Iterable[DrillResult]) -> List[str]:
    """Extract the post-drill preservation order as skill names."""

    ordered = sorted(results, key=lambda item: (not item.passed, item.score, item.stale_days, item.skill), reverse=True)
    return [item.skill for item in ordered]


__all__ = [
    "DrillFault",
    "DrillResult",
    "SkillCandidate",
    "build_decay_faults",
    "default_minimal_verify",
    "freshness_queue",
    "rank_stale_hot_skills",
    "run_skill_decay_drill",
]
