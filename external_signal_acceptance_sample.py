"""Runnable intake -> value -> evalbench sample for one external signal.

This module is intentionally small and dependency-light: it turns a single
outside observation into an intake record, derives a value requirement, then
builds and runs an evalbench-style acceptance case.

Run:
    python external_signal_acceptance_sample.py
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
import json
from typing import Any, Dict, List


@dataclass(frozen=True)
class IntakeRecord:
    signal_id: str
    source: str
    observation: str
    pain: str
    requested_change: str


@dataclass(frozen=True)
class ValueRequirement:
    requirement_id: str
    intake_signal_id: str
    user_value: str
    measurable_outcome: str
    non_goal: str


@dataclass(frozen=True)
class EvalbenchCase:
    case_id: str
    requirement_id: str
    prompt: str
    required_evidence: List[str]
    pass_threshold: int


def intake_observation(observation: str) -> IntakeRecord:
    """Normalize one outside observation into an intake record."""
    return IntakeRecord(
        signal_id="external-signal-acceptance-001",
        source="user_observation",
        observation=observation.strip(),
        pain="Evolution decisions are too easy to steer by intuition alone.",
        requested_change=(
            "Convert at least one real external observation into a runnable "
            "intake -> value -> evalbench acceptance example."
        ),
    )


def derive_value(record: IntakeRecord) -> ValueRequirement:
    """Translate the intake record into a user-value requirement."""
    return ValueRequirement(
        requirement_id="value-from-" + record.signal_id,
        intake_signal_id=record.signal_id,
        user_value=(
            "Future changes should be guided by a visible external-value loop, "
            "not only by internal preference or vague confidence."
        ),
        measurable_outcome=(
            "A runnable sample preserves the original observation, states the "
            "user value, and defines concrete evidence needed to pass."
        ),
        non_goal="Do not claim broad product validation from this single sample.",
    )


def build_evalbench_case(requirement: ValueRequirement) -> EvalbenchCase:
    """Create an evalbench-style acceptance case from the value requirement."""
    return EvalbenchCase(
        case_id="evalbench-" + requirement.requirement_id,
        requirement_id=requirement.requirement_id,
        prompt=(
            "Given an implemented change, verify that one external observation "
            "is traceable through intake, value, and evalbench acceptance."
        ),
        required_evidence=[
            "intake_record_contains_original_observation",
            "value_requirement_names_user_value",
            "evalbench_case_has_runnable_pass_fail_checks",
        ],
        pass_threshold=3,
    )


def run_evalbench_case(
    record: IntakeRecord, requirement: ValueRequirement, case: EvalbenchCase
) -> Dict[str, Any]:
    """Run the small acceptance check and return evalbench-like results."""
    checks = {
        "intake_record_contains_original_observation": bool(record.observation)
        and "观察" in record.observation,
        "value_requirement_names_user_value": bool(requirement.user_value)
        and requirement.intake_signal_id == record.signal_id,
        "evalbench_case_has_runnable_pass_fail_checks": bool(case.required_evidence)
        and case.pass_threshold <= len(case.required_evidence),
    }
    passed = sum(1 for ok in checks.values() if ok)
    return {
        "case_id": case.case_id,
        "requirement_id": case.requirement_id,
        "passed": passed >= case.pass_threshold,
        "passed_checks": passed,
        "needed_checks": case.pass_threshold,
        "checks": checks,
    }


def run_sample() -> Dict[str, Any]:
    """Execute the full intake -> value -> evalbench sample."""
    observation = (
        "今天推进“外界信号验收化”：把1条观察转成 intake→value→evalbench "
        "的可跑需求样例。因为我要少凭感觉进化，多让真实外界价值闭环指路。"
    )
    record = intake_observation(observation)
    requirement = derive_value(record)
    case = build_evalbench_case(requirement)
    result = run_evalbench_case(record, requirement, case)
    return {
        "intake": asdict(record),
        "value": asdict(requirement),
        "evalbench": asdict(case),
        "result": result,
    }


if __name__ == "__main__":
    print(json.dumps(run_sample(), ensure_ascii=False, indent=2))
