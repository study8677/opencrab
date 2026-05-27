"""End-to-end acceptance for the onboarding -> userlab contributor path.

This module is intentionally standalone: importing it has no side effects, while
``run_acceptance()`` validates that a new contributor can be guided through a
10-minute path and writes a JSONL evidence record for the userlab ledger.
"""

from __future__ import annotations

import importlib
import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


DEFAULT_LEDGER_PATH = Path(".crab") / "evidence" / "onboarding_userlab.jsonl"


@dataclass(frozen=True)
class OnboardingStep:
    """One bounded action in the new-contributor path."""

    name: str
    minutes: int
    evidence: str
    acceptance: str


@dataclass
class AcceptanceReport:
    """Structured result that can be stored as evidence."""

    passed: bool
    total_minutes: int
    checks: Dict[str, bool]
    steps: List[Dict[str, Any]]
    observed_modules: Dict[str, Dict[str, Any]]
    ledger_path: str
    timestamp: float = field(default_factory=time.time)

    def to_record(self) -> Dict[str, Any]:
        record = asdict(self)
        record["kind"] = "onboarding_userlab_acceptance"
        record["version"] = 1
        return record


def default_ten_minute_path() -> List[OnboardingStep]:
    """Return the canonical 10-minute path used for acceptance."""

    return [
        OnboardingStep(
            name="orient",
            minutes=2,
            evidence="contributor can identify the goal, safety rule, and edit format",
            acceptance="no prior repository knowledge required",
        ),
        OnboardingStep(
            name="run_smoke",
            minutes=2,
            evidence="contributor can run or reason about import/compile smoke checks",
            acceptance="the path names the verification gate explicitly",
        ),
        OnboardingStep(
            name="make_tiny_change",
            minutes=3,
            evidence="contributor can choose one small reversible Python change",
            acceptance="change is scoped enough to review in one screen",
        ),
        OnboardingStep(
            name="verify",
            minutes=2,
            evidence="contributor can connect the change to a pass/fail signal",
            acceptance="verification result is recorded rather than assumed",
        ),
        OnboardingStep(
            name="ledger_backfeed",
            minutes=1,
            evidence="contributor can append the outcome to an evidence ledger",
            acceptance="future contributors can inspect what happened",
        ),
    ]


def _module_probe(module_name: str) -> Dict[str, Any]:
    """Probe an optional module without assuming any project-specific API."""

    try:
        module = importlib.import_module(module_name)
    except Exception as exc:  # pragma: no cover - diagnostic path
        return {
            "importable": False,
            "error": f"{type(exc).__name__}: {exc}",
            "public_callables": [],
        }

    public_callables = []
    for name in dir(module):
        if name.startswith("_"):
            continue
        value = getattr(module, name)
        if callable(value):
            public_callables.append(name)

    return {
        "importable": True,
        "error": None,
        "public_callables": sorted(public_callables)[:25],
    }


def _write_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def evaluate_path(
    steps: Optional[Iterable[OnboardingStep]] = None,
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    write_ledger: bool = True,
) -> AcceptanceReport:
    """Evaluate the onboarding -> userlab path and optionally backfeed evidence."""

    chosen_steps = list(steps if steps is not None else default_ten_minute_path())
    total_minutes = sum(step.minutes for step in chosen_steps)
    step_names = {step.name for step in chosen_steps}
    required_steps = {
        "orient",
        "run_smoke",
        "make_tiny_change",
        "verify",
        "ledger_backfeed",
    }

    observed_modules = {
        "onboarding": _module_probe("onboarding"),
        "userlab": _module_probe("userlab"),
    }

    checks = {
        "within_ten_minutes": total_minutes <= 10,
        "has_required_steps": required_steps.issubset(step_names),
        "all_steps_have_evidence": all(bool(step.evidence.strip()) for step in chosen_steps),
        "all_steps_have_acceptance": all(bool(step.acceptance.strip()) for step in chosen_steps),
        "onboarding_importable": observed_modules["onboarding"]["importable"],
        "userlab_importable": observed_modules["userlab"]["importable"],
    }

    report = AcceptanceReport(
        passed=all(checks.values()),
        total_minutes=total_minutes,
        checks=checks,
        steps=[asdict(step) for step in chosen_steps],
        observed_modules=observed_modules,
        ledger_path=str(ledger_path),
    )

    if write_ledger:
        _write_jsonl(ledger_path, report.to_record())

    return report


def run_acceptance(
    ledger_path: str | Path = DEFAULT_LEDGER_PATH,
    *,
    write_ledger: bool = True,
) -> AcceptanceReport:
    """Public entry point for the onboarding -> userlab acceptance run."""

    return evaluate_path(Path(ledger_path), write_ledger=write_ledger)


def main() -> int:
    report = run_acceptance()
    print(json.dumps(report.to_record(), ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
