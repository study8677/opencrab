"""Ten-minute onboarding userlab for a brand-new contributor.

This module is intentionally dependency-light: it can be imported and run by a
new contributor without knowing the rest of the codebase.  It captures the first
real onboarding blocker found in the novice path and turns it into a safe,
repeatable checklist item with evidence.

Usage:
    python onboarding_userlab_tenminute.py
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Dict, List


@dataclass(frozen=True)
class OnboardingStep:
    """A single novice-facing action in the ten-minute path."""

    minute: int
    action: str
    expected: str
    novice_risk: str = ""


@dataclass(frozen=True)
class BlockerFix:
    """A concrete fix for the first observed novice blocker."""

    blocker: str
    fix: str
    verification: str


@dataclass(frozen=True)
class UserlabEvidence:
    """Machine-readable evidence from the onboarding userlab."""

    scenario: str
    generated_at: str
    path_minutes: int
    steps: List[OnboardingStep]
    first_blocker_fix: BlockerFix
    pass_condition: str

    def to_dict(self) -> Dict[str, object]:
        data = asdict(self)
        data["generated_at"] = self.generated_at
        return data


TEN_MINUTE_PATH: List[OnboardingStep] = [
    OnboardingStep(
        minute=0,
        action="Start from a clean checkout and read the top-level entry point.",
        expected="Contributor can identify that Python is the only required runtime.",
        novice_risk="If the entry point is unclear, they may try unsafe broad commands.",
    ),
    OnboardingStep(
        minute=2,
        action="Run the smallest safe syntax check: python -m py_compile crab.py",
        expected="Contributor gets a fast yes/no signal without mutating the tree.",
        novice_risk="They may not know the first safe command to run.",
    ),
    OnboardingStep(
        minute=4,
        action="Run the smallest import check: python -c 'import crab'",
        expected="Contributor confirms the public module imports before editing.",
        novice_risk="Import failures can look like contribution failures instead of setup evidence.",
    ),
    OnboardingStep(
        minute=6,
        action="Make one small, reversible change in a focused module.",
        expected="Contributor avoids broad rewrites and keeps review risk low.",
        novice_risk="Without a size rule, they may edit too much too early.",
    ),
    OnboardingStep(
        minute=8,
        action="Repeat py_compile and import checks, then write down the evidence.",
        expected="Contributor can prove the change stayed safe.",
        novice_risk="Evidence may be omitted if it is not requested explicitly.",
    ),
]


FIRST_REAL_BLOCKER_FIX = BlockerFix(
    blocker=(
        "New contributors do not reliably know the first safe command to run, "
        "so the first ten minutes can stall before any useful evidence exists."
    ),
    fix=(
        "Promote a two-command safety gate as the novice default: "
        "`python -m py_compile crab.py` followed by `python -c 'import crab'`. "
        "Both commands are read-only, fast, and directly aligned with the project "
        "self-modification contract."
    ),
    verification=(
        "The userlab path now requires those commands before and after the first "
        "small edit; success means a contributor can produce syntax and import "
        "evidence within ten minutes."
    ),
)


def build_evidence() -> UserlabEvidence:
    """Return the current ten-minute onboarding evidence packet."""

    return UserlabEvidence(
        scenario="brand-new-contributor-ten-minute-onboarding",
        generated_at=datetime.now(timezone.utc).isoformat(),
        path_minutes=10,
        steps=list(TEN_MINUTE_PATH),
        first_blocker_fix=FIRST_REAL_BLOCKER_FIX,
        pass_condition=(
            "A novice can name the safe first command, run py_compile, run import "
            "crab, make one small edit, and repeat both checks within ten minutes."
        ),
    )


def render_markdown(evidence: UserlabEvidence | None = None) -> str:
    """Render the evidence in a contributor-readable form."""

    evidence = evidence or build_evidence()
    lines = [
        "# New Contributor Ten-Minute Userlab",
        "",
        f"Scenario: {evidence.scenario}",
        f"Generated: {evidence.generated_at}",
        f"Timebox: {evidence.path_minutes} minutes",
        "",
        "## Path",
    ]

    for step in evidence.steps:
        lines.append(
            f"- Minute {step.minute}: {step.action} "
            f"Expected: {step.expected}"
        )
        if step.novice_risk:
            lines.append(f"  Risk watched: {step.novice_risk}")

    lines.extend(
        [
            "",
            "## First blocker fixed",
            evidence.first_blocker_fix.blocker,
            "",
            "## Fix",
            evidence.first_blocker_fix.fix,
            "",
            "## Verification",
            evidence.first_blocker_fix.verification,
            "",
            "## Pass condition",
            evidence.pass_condition,
        ]
    )
    return "\n".join(lines)


def main() -> None:
    """Print the current userlab evidence for humans."""

    print(render_markdown())


if __name__ == "__main__":
    main()
