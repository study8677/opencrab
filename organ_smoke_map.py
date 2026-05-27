"""Organ cooperation smoke map.

This module probes a few high-value journeys without executing risky side
effects.  It records which organs can be imported, which expected callable is
present, where the chain breaks, and the smallest fallback route that still
keeps the journey alive.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import importlib
import json
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class OrganStep:
    """One expected organ hop in a journey."""

    organ: str
    role: str
    callables: Sequence[str] = ()


@dataclass(frozen=True)
class StepProbe:
    """Observed status for one organ hop."""

    organ: str
    role: str
    status: str
    callable: Optional[str] = None
    breakpoint: Optional[str] = None


@dataclass(frozen=True)
class JourneyProbe:
    """Observed status for one end-to-end smoke journey."""

    name: str
    purpose: str
    chain: Sequence[StepProbe]
    breakpoints: Sequence[str]
    minimal_alternative_path: Sequence[StepProbe]
    alive: bool


@dataclass(frozen=True)
class JourneySpec:
    """A critical journey and its minimum viable substitute route."""

    name: str
    purpose: str
    chain: Sequence[OrganStep]
    fallback: Sequence[OrganStep]


JOURNEYS: Sequence[JourneySpec] = (
    JourneySpec(
        name="patch_landing",
        purpose="从意图进入补丁落地，确认手、验证、回归能接成一条活路。",
        chain=(
            OrganStep("intent", "parse user intent", ("parse_intent", "detect_intent", "Intent")),
            OrganStep("planner", "shape repair plan", ("plan", "make_plan", "Planner")),
            OrganStep("hands", "apply bounded code change", ("apply_patch", "write_patch", "Hands")),
            OrganStep("organ_verification", "verify touched organ", ("verify", "verify_organ", "OrganVerification")),
            OrganStep("regression", "run regression guard", ("run", "run_regression", "Regression")),
        ),
        fallback=(
            OrganStep("smoke", "minimum compile/import smoke", ("run", "smoke", "main")),
            OrganStep("checkup", "broad health check", ("run", "check", "main")),
        ),
    ),
    JourneySpec(
        name="evidence_release_gate",
        purpose="从证据收集到发布闸门，确认事实、时效、冲突和放行判断能联动。",
        chain=(
            OrganStep("evidence", "collect support evidence", ("collect", "record", "Evidence")),
            OrganStep("evidence_freshness", "check evidence freshness", ("check", "score", "main")),
            OrganStep("evidence_circuitbreaker", "stop fragile evidence path", ("check", "trip", "CircuitBreaker")),
            OrganStep("releasegate", "decide release readiness", ("decide", "gate", "ReleaseGate")),
        ),
        fallback=(
            OrganStep("safetycase", "manual safety case summary", ("build", "summarize", "SafetyCase")),
            OrganStep("release_drill", "release rehearsal instead of direct gate", ("run", "rehearse", "main")),
        ),
    ),
    JourneySpec(
        name="onboarding_feedback_loop",
        purpose="从新手旅程到反馈去重与交接，确认用户价值回路不只停在单器官。",
        chain=(
            OrganStep("onboarding", "start onboarding path", ("start", "run", "Onboarding")),
            OrganStep("onboarding_userlab_tenminute", "ten minute user lab", ("run", "simulate", "main")),
            OrganStep("userlab", "capture user observation", ("record", "run", "UserLab")),
            OrganStep("feedback_dedup", "deduplicate feedback", ("dedup", "deduplicate", "main")),
            OrganStep("handoff", "handoff actionable result", ("handoff", "transfer", "main")),
        ),
        fallback=(
            OrganStep("showcase", "surface known working path", ("render", "show", "main")),
            OrganStep("changelog", "leave auditable user-facing trace", ("append", "write", "main")),
        ),
    ),
)


def _first_present_callable(module_name: str, candidates: Iterable[str]) -> StepProbe:
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - diagnostic path
        return StepProbe(
            organ=module_name,
            role="import",
            status="break",
            breakpoint=f"import failed: {exc.__class__.__name__}: {exc}",
        )

    candidate_list = tuple(candidates)
    if not candidate_list:
        return StepProbe(organ=module_name, role="import", status="ok")

    for name in candidate_list:
        value = getattr(module, name, None)
        if callable(value):
            return StepProbe(organ=module_name, role="callable", status="ok", callable=name)

    return StepProbe(
        organ=module_name,
        role="callable",
        status="break",
        breakpoint="no expected callable: " + ", ".join(candidate_list),
    )


def _probe_step(step: OrganStep) -> StepProbe:
    probed = _first_present_callable(step.organ, step.callables)
    return StepProbe(
        organ=probed.organ,
        role=step.role,
        status=probed.status,
        callable=probed.callable,
        breakpoint=probed.breakpoint,
    )


def probe_journey(spec: JourneySpec) -> JourneyProbe:
    """Probe one journey without invoking the discovered callables."""

    chain: List[StepProbe] = [_probe_step(step) for step in spec.chain]
    breakpoints = [
        f"{item.organ}: {item.breakpoint}"
        for item in chain
        if item.status != "ok" and item.breakpoint
    ]
    fallback = [_probe_step(step) for step in spec.fallback]
    fallback_alive = all(item.status == "ok" for item in fallback)
    return JourneyProbe(
        name=spec.name,
        purpose=spec.purpose,
        chain=chain,
        breakpoints=breakpoints,
        minimal_alternative_path=fallback,
        alive=not breakpoints or fallback_alive,
    )


def smoke_map() -> List[JourneyProbe]:
    """Return the three critical organ-cooperation smoke journeys."""

    return [probe_journey(spec) for spec in JOURNEYS]


def as_dict() -> dict:
    """Return a JSON-friendly smoke map."""

    return {"journeys": [asdict(item) for item in smoke_map()]}


def render_text() -> str:
    """Render a compact human-readable smoke map."""

    lines: List[str] = ["organ cooperation smoke map"]
    for journey in smoke_map():
        lines.append(f"- {journey.name}: {'ALIVE' if journey.alive else 'BROKEN'}")
        lines.append(f"  purpose: {journey.purpose}")
        lines.append("  actual_chain:")
        for step in journey.chain:
            suffix = f" via {step.callable}" if step.callable else ""
            bp = f" [{step.breakpoint}]" if step.breakpoint else ""
            lines.append(f"    - {step.organ}: {step.status}{suffix} / {step.role}{bp}")
        if journey.breakpoints:
            lines.append("  breakpoints:")
            for item in journey.breakpoints:
                lines.append(f"    - {item}")
        lines.append("  minimal_alternative_path:")
        for step in journey.minimal_alternative_path:
            suffix = f" via {step.callable}" if step.callable else ""
            bp = f" [{step.breakpoint}]" if step.breakpoint else ""
            lines.append(f"    - {step.organ}: {step.status}{suffix}{bp}")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Use --json for machine-readable output."""

    args = list(argv or ())
    if "--json" in args:
        print(json.dumps(as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(render_text())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
