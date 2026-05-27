"""Brain-only two-file self-drill helpers.

This module keeps a tiny, dependency-light model of the intended path:

    tiergate -> touchgraph -> patchfitroom

It is deliberately pure and import-safe so it can be used as a low-risk
practice target for controlled two-file changes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


@dataclass(frozen=True)
class DrillPlan:
    """A compact description of one controlled self-edit drill."""

    intent: str
    files: Tuple[str, ...]
    tier: str
    touch_edges: Tuple[Tuple[str, str], ...]
    fit_checks: Tuple[str, ...]

    @property
    def is_two_file(self) -> bool:
        return len(self.files) == 2

    @property
    def is_brain_only(self) -> bool:
        return "external-tool" not in self.fit_checks


def _clean_items(items: Iterable[str]) -> Tuple[str, ...]:
    cleaned = tuple(item.strip() for item in items if item and item.strip())
    return cleaned


def tiergate_classify(files: Iterable[str]) -> str:
    """Classify a planned edit size for a cautious self-modification gate."""

    cleaned = _clean_items(files)
    if len(cleaned) <= 1:
        return "single-file"
    if len(cleaned) == 2:
        return "controlled-two-file"
    return "multi-file-risk"


def touchgraph_edges(files: Iterable[str]) -> Tuple[Tuple[str, str], ...]:
    """Return a minimal ordered touchgraph for the files in a drill."""

    cleaned = _clean_items(files)
    if len(cleaned) < 2:
        return ()
    return tuple((cleaned[index], cleaned[index + 1]) for index in range(len(cleaned) - 1))


def patchfitroom_checks(tier: str, edges: Iterable[Tuple[str, str]]) -> Tuple[str, ...]:
    """Name the checks that should be satisfied before a patch leaves rehearsal."""

    checks = ["py-compile", "import-crab"]
    if tier == "controlled-two-file":
        checks.append("two-file-scope")
    if tuple(edges):
        checks.append("touchgraph-linked")
    return tuple(checks)


def build_drill_plan(intent: str, files: Iterable[str]) -> DrillPlan:
    """Build a brain-only plan for a small self-edit drill."""

    cleaned = _clean_items(files)
    tier = tiergate_classify(cleaned)
    edges = touchgraph_edges(cleaned)
    checks = patchfitroom_checks(tier, edges)
    return DrillPlan(
        intent=intent.strip() or "self-drill",
        files=cleaned,
        tier=tier,
        touch_edges=edges,
        fit_checks=checks,
    )


def accepts_controlled_two_file(plan: DrillPlan) -> bool:
    """Return whether the plan satisfies the intended drill constraints."""

    return (
        plan.is_two_file
        and plan.tier == "controlled-two-file"
        and bool(plan.touch_edges)
        and "two-file-scope" in plan.fit_checks
        and "touchgraph-linked" in plan.fit_checks
        and plan.is_brain_only
    )


__all__ = [
    "DrillPlan",
    "accepts_controlled_two_file",
    "build_drill_plan",
    "patchfitroom_checks",
    "tiergate_classify",
    "touchgraph_edges",
]
