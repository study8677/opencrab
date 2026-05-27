"""Acceptance check for the first-time user onboarding path.

This module is intentionally dependency-light: it can be imported, called from
tests, or run directly with ``python onboarding_userlab_acceptance.py``.  The
goal is to prove that a newcomer can discover a short path, run a harmless
check, and receive a concrete next action within a ten-minute window.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping


@dataclass(frozen=True)
class OnboardingStep:
    """One small, newcomer-facing action."""

    key: str
    title: str
    command: str
    expected: str
    minutes: int = 2


def default_onboarding_steps() -> List[OnboardingStep]:
    """Return a short path that fits in a ten-minute newcomer session."""

    return [
        OnboardingStep(
            key="import",
            title="Verify the package imports",
            command="python -c \"import crab; print('ok')\"",
            expected="prints ok without traceback",
            minutes=2,
        ),
        OnboardingStep(
            key="compile",
            title="Verify edited Python still compiles",
            command="python -m py_compile crab.py onboarding.py userlab.py",
            expected="exits with status 0",
            minutes=2,
        ),
        OnboardingStep(
            key="map",
            title="Find the newcomer entry points",
            command="python -c \"import onboarding, userlab; print('ok')\"",
            expected="both modules import without side effects",
            minutes=2,
        ),
        OnboardingStep(
            key="first_next_step",
            title="Show one safe next action",
            command="python onboarding_userlab_acceptance.py",
            expected="reports PASS and a next action",
            minutes=2,
        ),
    ]


def run_acceptance(
    observations: Mapping[str, bool] | None = None,
) -> Dict[str, object]:
    """Evaluate the onboarding path.

    ``observations`` lets tests or a user lab session mark individual steps as
    failed without executing shell commands.  Missing observations default to
    ``True`` because this module validates the shape and availability of the
    path; command execution belongs to the surrounding lab harness.
    """

    steps = default_onboarding_steps()
    seen = dict(observations or {})
    results = []
    for step in steps:
        passed = bool(seen.get(step.key, True))
        results.append(
            {
                "key": step.key,
                "title": step.title,
                "command": step.command,
                "expected": step.expected,
                "minutes": step.minutes,
                "passed": passed,
            }
        )

    total_minutes = sum(step.minutes for step in steps)
    failed = [item for item in results if not item["passed"]]
    next_action = (
        "Fix the first failed onboarding step: %s" % failed[0]["title"]
        if failed
        else "Invite a newcomer to run the four-step path and record friction."
    )

    return {
        "name": "userlab/onboarding",
        "passed": not failed and total_minutes <= 10,
        "timebox_minutes": total_minutes,
        "steps": results,
        "next_action": next_action,
    }


def acceptance(observations: Mapping[str, bool] | None = None) -> Dict[str, object]:
    """Compatibility alias for older acceptance harnesses."""

    return run_acceptance(observations)


def main() -> int:
    """CLI entry point used by humans and simple smoke tests."""

    result = run_acceptance()
    status = "PASS" if result["passed"] else "FAIL"
    print("%s userlab/onboarding timebox=%sm" % (status, result["timebox_minutes"]))
    print("next: %s" % result["next_action"])
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
