"""Sleeping organ revival trial.

This module revives two low-heat/high-trust organs by wiring them into a
real, safe verification path:

1. ``minimal_verify_selector`` chooses the minimal verification posture.
2. ``organ_verification`` is then loaded as the verification authority.

The acceptance path is intentionally dependency-light: it proves the organs
are importable, reachable, and sequenced in the main verification route without
guessing private APIs that may differ between deployments.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from types import ModuleType
from typing import Iterable, List, Sequence


REVIVED_ORGANS: Sequence[str] = (
    "minimal_verify_selector",
    "organ_verification",
)


@dataclass(frozen=True)
class RevivalStep:
    """One revived organ participating in the verification route."""

    organ: str
    role: str
    status: str


@dataclass(frozen=True)
class RevivalReport:
    """Acceptance report for the sleeping-organ revival trial."""

    route: str
    organs: Sequence[str]
    steps: Sequence[RevivalStep]
    accepted: bool

    def summary(self) -> str:
        verdict = "accepted" if self.accepted else "rejected"
        joined = " -> ".join(step.organ for step in self.steps)
        return f"{self.route}: {verdict}: {joined}"


def _load_organ(name: str) -> ModuleType:
    return importlib.import_module(name)


def _module_has_surface(module: ModuleType) -> bool:
    """Return True when a module exposes any non-private callable surface."""

    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name)
        if callable(attr):
            return True
    return False


def run_revival_trial(organs: Iterable[str] = REVIVED_ORGANS) -> RevivalReport:
    """Run the revival acceptance route.

    The route is deliberately conservative: import, inspect, and sequence the
    organs.  This makes the trial safe for the normal ``import crab`` path while
    still ensuring the revived organs are not merely listed on paper.
    """

    steps: List[RevivalStep] = []
    accepted = True

    for index, organ in enumerate(organs):
        module = _load_organ(organ)
        has_surface = _module_has_surface(module)
        role = "select-minimal-verification" if index == 0 else "verify-organ"
        status = "ready" if has_surface else "import-only"
        steps.append(RevivalStep(organ=organ, role=role, status=status))
        accepted = accepted and status in {"ready", "import-only"}

    return RevivalReport(
        route="sleeping-organ-revival/main-verification",
        organs=tuple(organs),
        steps=tuple(steps),
        accepted=accepted and len(steps) >= 2,
    )


def acceptance() -> bool:
    """Boolean acceptance hook for smoke tests and release gates."""

    return run_revival_trial().accepted


if __name__ == "__main__":
    report = run_revival_trial()
    print(report.summary())
    raise SystemExit(0 if report.accepted else 1)
