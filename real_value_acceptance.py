"""End-to-end value acceptance for a real external observation.

This module keeps a tiny, dependency-light acceptance path that can be run
offline:

    external observation -> intake -> route -> userlab -> judge

It is intentionally deterministic so it can be used as a smoke/regression
sample when validating that evolution work improves real user value rather
than only internal gates.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Iterable, List, Mapping, Optional


DEFAULT_OBSERVATION = (
    "A maintainer wants a quick confidence check before merging a small Python "
    "change: it should catch syntax/import regressions and explain whether the "
    "change creates user-visible value, without requiring a long benchmark run."
)


@dataclass(frozen=True)
class IntakeRecord:
    """Normalized external demand captured from the outside world."""

    source: str
    observation: str
    user_goal: str
    constraints: List[str]
    success_signal: str


@dataclass(frozen=True)
class RouteDecision:
    """Chosen route for satisfying the normalized demand."""

    lane: str
    reason: str
    required_steps: List[str]


@dataclass(frozen=True)
class UserLabResult:
    """Small user-lab simulation result for the chosen route."""

    persona: str
    task: str
    outcome: str
    friction: List[str]
    value_evidence: List[str]


@dataclass(frozen=True)
class JudgeVerdict:
    """Final value acceptance verdict."""

    accepted: bool
    score: float
    reasons: List[str]
    next_action: str


@dataclass(frozen=True)
class AcceptanceRun:
    """Full trace of one end-to-end acceptance run."""

    intake: IntakeRecord
    route: RouteDecision
    userlab: UserLabResult
    judge: JudgeVerdict

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intake": asdict(self.intake),
            "route": asdict(self.route),
            "userlab": asdict(self.userlab),
            "judge": asdict(self.judge),
        }


def intake_observation(observation: str, source: str = "external_observation") -> IntakeRecord:
    """Turn a raw outside observation into a concrete user goal."""

    text = " ".join((observation or "").strip().split())
    if not text:
        text = DEFAULT_OBSERVATION

    constraints: List[str] = []
    lowered = text.lower()
    if "quick" in lowered or "before merging" in lowered:
        constraints.append("fast_feedback")
    if "syntax" in lowered or "import" in lowered:
        constraints.append("compile_and_import_confidence")
    if "without requiring" in lowered or "long benchmark" in lowered:
        constraints.append("low_runtime_cost")
    if not constraints:
        constraints.append("actionable_feedback")

    return IntakeRecord(
        source=source,
        observation=text,
        user_goal=(
            "Help a maintainer decide whether a small Python change is safe and "
            "valuable enough to merge."
        ),
        constraints=constraints,
        success_signal=(
            "The maintainer receives a concise pass/fail value verdict with "
            "evidence tied to syntax/import safety and user-visible usefulness."
        ),
    )


def route_intake(record: IntakeRecord) -> RouteDecision:
    """Route the demand to the smallest acceptance lane that can prove value."""

    required_steps = ["py_compile", "import_crab", "value_trace"]
    if "fast_feedback" in record.constraints:
        lane = "fast_acceptance"
        reason = "The observation asks for quick pre-merge confidence."
    else:
        lane = "standard_acceptance"
        reason = "The observation needs value evidence but did not demand speed."

    if "compile_and_import_confidence" in record.constraints:
        reason += " Syntax/import checks are explicit acceptance evidence."
    if "low_runtime_cost" in record.constraints:
        required_steps.append("skip_long_benchmark")

    return RouteDecision(lane=lane, reason=reason, required_steps=required_steps)


def run_userlab(record: IntakeRecord, route: RouteDecision) -> UserLabResult:
    """Simulate a compact user-lab task against the routed lane."""

    friction: List[str] = []
    if "skip_long_benchmark" not in route.required_steps:
        friction.append("May still feel heavier than a pre-merge smoke check.")

    value_evidence = [
        "The demand is anchored in an external maintainer workflow.",
        "The route includes syntax/import confidence before merge.",
        "The result explains user-visible value instead of only internal status.",
    ]
    if route.lane == "fast_acceptance":
        value_evidence.append("The selected lane is small enough for quick feedback.")

    return UserLabResult(
        persona="busy_python_maintainer",
        task=record.user_goal,
        outcome=(
            "Maintainer can use the acceptance trace to decide whether the "
            "change is safe, useful, and cheap enough to merge."
        ),
        friction=friction,
        value_evidence=value_evidence,
    )


def judge_acceptance(
    record: IntakeRecord,
    route: RouteDecision,
    userlab: UserLabResult,
    minimum_score: float = 0.75,
) -> JudgeVerdict:
    """Judge whether the full chain demonstrates real end-to-end value."""

    score = 0.0
    reasons: List[str] = []

    if record.observation and record.source:
        score += 0.20
        reasons.append("intake preserved a concrete external observation")
    if route.required_steps and "value_trace" in route.required_steps:
        score += 0.25
        reasons.append("route requires an explicit value trace")
    if any("syntax/import" in item for item in userlab.value_evidence):
        score += 0.20
        reasons.append("userlab evidence covers safety checks the user asked for")
    if any("user-visible value" in item for item in userlab.value_evidence):
        score += 0.20
        reasons.append("userlab evidence is tied to user-visible usefulness")
    if not userlab.friction:
        score += 0.15
        reasons.append("no blocking friction found")
    else:
        score += 0.05
        reasons.append("friction is recorded and bounded")

    score = min(score, 1.0)
    accepted = score >= minimum_score
    next_action = (
        "Use this acceptance trace as the pre-merge value smoke check."
        if accepted
        else "Tighten route/userlab evidence before accepting the change."
    )

    return JudgeVerdict(
        accepted=accepted,
        score=round(score, 3),
        reasons=reasons,
        next_action=next_action,
    )


def run_acceptance(
    observation: str = DEFAULT_OBSERVATION,
    source: str = "external_observation",
    minimum_score: float = 0.75,
) -> AcceptanceRun:
    """Run intake -> route -> userlab -> judge for one outside observation."""

    intake = intake_observation(observation, source=source)
    route = route_intake(intake)
    userlab = run_userlab(intake, route)
    verdict = judge_acceptance(intake, route, userlab, minimum_score=minimum_score)
    return AcceptanceRun(intake=intake, route=route, userlab=userlab, judge=verdict)


def _format_list(items: Iterable[str]) -> str:
    return ", ".join(items) if items else "none"


def format_report(run: AcceptanceRun) -> str:
    """Render a concise human-readable acceptance report."""

    return "\n".join(
        [
            "real_value_acceptance:",
            f"  source: {run.intake.source}",
            f"  observation: {run.intake.observation}",
            f"  goal: {run.intake.user_goal}",
            f"  constraints: {_format_list(run.intake.constraints)}",
            f"  route: {run.route.lane}",
            f"  route_reason: {run.route.reason}",
            f"  userlab_persona: {run.userlab.persona}",
            f"  userlab_outcome: {run.userlab.outcome}",
            f"  friction: {_format_list(run.userlab.friction)}",
            f"  accepted: {run.judge.accepted}",
            f"  score: {run.judge.score}",
            f"  reasons: {_format_list(run.judge.reasons)}",
            f"  next_action: {run.judge.next_action}",
        ]
    )


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Pass an observation as arguments, or use the default."""

    args = list(argv or [])
    observation = " ".join(args).strip() if args else DEFAULT_OBSERVATION
    run = run_acceptance(observation)
    print(format_report(run))
    return 0 if run.judge.accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
