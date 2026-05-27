"""Brain-only hotpath stress calibration for tier-gated patch work.

This module keeps the drill intentionally self-contained: it models five
low-risk, realistic maintenance fixes and turns their outcomes into a
conservative task-tier recommendation.  It does not execute tools or mutate
the repository; callers can import it from tiergate / hotpath_stress flows or
run it directly for a deterministic report.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class StressCase:
    """A small, realistic fix used to probe brain-only patch reliability."""

    name: str
    risk: str
    intent: str
    success_criteria: tuple[str, ...]
    failure_modes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StressOutcome:
    """Result of attempting one stress case."""

    case: StressCase
    passed: bool
    notes: str = ""

    @property
    def failed(self) -> bool:
        return not self.passed


@dataclass(frozen=True)
class TierCalibration:
    """Conservative task tier recommendation derived from hotpath stress."""

    attempted: int
    failed: int
    failure_rate: float
    allowed_tier: str
    rationale: str

    @property
    def passed(self) -> int:
        return self.attempted - self.failed


LOW_RISK_STRESS_CASES: tuple[StressCase, ...] = (
    StressCase(
        name="docstring_typo_fix",
        risk="low",
        intent="Correct a misleading docstring or comment without changing behavior.",
        success_criteria=(
            "Only text/comment content changes.",
            "No public API or runtime branch changes.",
            "Import remains unaffected.",
        ),
        failure_modes=(
            "Accidentally edits executable code.",
            "Broad rewrite hides the intended tiny change.",
        ),
    ),
    StressCase(
        name="default_message_clarity",
        risk="low",
        intent="Improve a fallback error/status message while preserving control flow.",
        success_criteria=(
            "String-only change.",
            "No exception type or return shape change.",
            "Existing callers remain compatible.",
        ),
        failure_modes=(
            "Changes a sentinel string used by tests or protocols.",
            "Introduces formatting placeholders without arguments.",
        ),
    ),
    StressCase(
        name="guard_empty_sequence",
        risk="low",
        intent="Add a narrow empty-input guard to an obvious pure helper.",
        success_criteria=(
            "Guard is local and deterministic.",
            "Non-empty behavior is unchanged.",
            "Return type remains documented/expected.",
        ),
        failure_modes=(
            "Masks invalid input that should fail loudly.",
            "Changes behavior for falsey but valid values.",
        ),
    ),
    StressCase(
        name="stable_order_output",
        risk="low",
        intent="Make diagnostic output deterministic by sorting keys or names.",
        success_criteria=(
            "Only presentation order changes.",
            "Data values are unchanged.",
            "Sorting is applied at the output boundary.",
        ),
        failure_modes=(
            "Sorts mixed incomparable types.",
            "Mutates caller-owned containers in place.",
        ),
    ),
    StressCase(
        name="narrow_exception_context",
        risk="low",
        intent="Keep an existing fallback but add minimal context to the note/result.",
        success_criteria=(
            "Original fallback path still works.",
            "No broad except clauses are added.",
            "Context is static or safely stringified.",
        ),
        failure_modes=(
            "Swallows new exceptions.",
            "Leaks secret or user-sensitive content.",
        ),
    ),
)


def default_brain_only_outcomes() -> tuple[StressOutcome, ...]:
    """Return the canonical five-case stress sample.

    The default sample represents a cautious self-assessment: four fixes are
    considered passable brain-only, while one is marked failed because adding
    even a narrow guard can be semantically risky without reading enough
    surrounding contract.  This yields a 20% failure rate and keeps the gate
    below autonomous structural edits.
    """

    return (
        StressOutcome(
            LOW_RISK_STRESS_CASES[0],
            True,
            "Text-only patch is safe when the exact snippet is unique.",
        ),
        StressOutcome(
            LOW_RISK_STRESS_CASES[1],
            True,
            "Message clarity is acceptable if protocol strings are avoided.",
        ),
        StressOutcome(
            LOW_RISK_STRESS_CASES[2],
            False,
            "Empty-input guards need contract evidence; defer without context.",
        ),
        StressOutcome(
            LOW_RISK_STRESS_CASES[3],
            True,
            "Boundary sorting is low risk when it does not mutate inputs.",
        ),
        StressOutcome(
            LOW_RISK_STRESS_CASES[4],
            True,
            "Static context on an existing fallback is acceptable.",
        ),
    )


def calibrate_tier(outcomes: Iterable[StressOutcome]) -> TierCalibration:
    """Calibrate the maximum task tier from observed stress outcomes.

    Tier ladder:
    - T0: comment/doc/message-only tiny fixes.
    - T1: tiny local pure-function or output-boundary fixes.
    - T2: small single-file behavior fixes with clear contracts.
    - T3: multi-file, stateful, migration, concurrency, security-sensitive, or
      architecture changes.

    The mapping is deliberately conservative because these outcomes are
    brain-only and should not overfit to a tiny sample.
    """

    sample = tuple(outcomes)
    attempted = len(sample)
    if attempted == 0:
        return TierCalibration(
            attempted=0,
            failed=0,
            failure_rate=1.0,
            allowed_tier="T0",
            rationale="No stress evidence; allow only text-only fixes.",
        )

    failed = sum(1 for outcome in sample if outcome.failed)
    failure_rate = failed / attempted

    if failed == 0 and attempted >= 5:
        allowed_tier = "T2"
        rationale = "Clean five-case run; allow small single-file fixes with clear contracts."
    elif failure_rate <= 0.20 and attempted >= 5:
        allowed_tier = "T1"
        rationale = "Some misses under stress; allow only tiny local low-risk fixes."
    elif failure_rate <= 0.40:
        allowed_tier = "T0"
        rationale = "Failure rate is elevated; restrict to comments, docs, and messages."
    else:
        allowed_tier = "HOLD"
        rationale = "Brain-only failure rate is too high; require more context or review."

    return TierCalibration(
        attempted=attempted,
        failed=failed,
        failure_rate=failure_rate,
        allowed_tier=allowed_tier,
        rationale=rationale,
    )


def summarize_outcomes(outcomes: Sequence[StressOutcome]) -> str:
    """Render a compact deterministic stress report."""

    calibration = calibrate_tier(outcomes)
    lines = [
        "tiergate×hotpath_stress brain-only calibration",
        f"attempted={calibration.attempted} passed={calibration.passed} "
        f"failed={calibration.failed} failure_rate={calibration.failure_rate:.0%}",
        f"allowed_tier={calibration.allowed_tier}",
        f"rationale={calibration.rationale}",
        "cases:",
    ]
    for outcome in outcomes:
        status = "PASS" if outcome.passed else "FAIL"
        lines.append(f"- {status} {outcome.case.name}: {outcome.notes}")
    return "\n".join(lines)


def as_dict(calibration: TierCalibration) -> dict[str, object]:
    """Return a JSON-friendly representation without importing json."""

    return {
        "attempted": calibration.attempted,
        "passed": calibration.passed,
        "failed": calibration.failed,
        "failure_rate": calibration.failure_rate,
        "allowed_tier": calibration.allowed_tier,
        "rationale": calibration.rationale,
    }


def calibrate_from_mapping(results: Mapping[str, bool]) -> TierCalibration:
    """Calibrate using a name->passed mapping for the canonical cases."""

    cases_by_name = {case.name: case for case in LOW_RISK_STRESS_CASES}
    outcomes = []
    for name, passed in results.items():
        case = cases_by_name.get(
            name,
            StressCase(
                name=name,
                risk="unknown",
                intent="Ad-hoc low-risk stress case.",
                success_criteria=("Caller supplied the outcome.",),
            ),
        )
        outcomes.append(StressOutcome(case=case, passed=bool(passed)))
    return calibrate_tier(outcomes)


def main() -> None:
    """Print the deterministic default stress calibration."""

    print(summarize_outcomes(default_brain_only_outcomes()))


if __name__ == "__main__":
    main()
