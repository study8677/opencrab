"""Planner-facing acceptance helpers for navlog move-card decisions.

The planner evolves only when a navlog/moveset card changes a decision.
This module gives planner code a small, deterministic way to record which
cards were used, which were rejected, and why.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, MutableMapping


DECISION_LOG_KEY = "navlog_move_card_decisions"


@dataclass(frozen=True)
class MoveCardDecision:
    """A single planner decision about one navlog move card."""

    card: str
    status: str
    reason: str
    changed_decision: bool = False
    evidence: tuple[str, ...] = field(default_factory=tuple)

    def as_dict(self) -> dict[str, Any]:
        return {
            "card": self.card,
            "status": self.status,
            "reason": self.reason,
            "changed_decision": self.changed_decision,
            "evidence": list(self.evidence),
        }


def _card_name(card: Any) -> str:
    if isinstance(card, str):
        return card
    if isinstance(card, Mapping):
        for key in ("name", "card", "id", "title"):
            value = card.get(key)
            if value:
                return str(value)
    return str(card)


def _string_set(values: Iterable[Any] | None) -> set[str]:
    if not values:
        return set()
    return {_card_name(value) for value in values if _card_name(value)}


def build_move_card_decisions(
    candidates: Iterable[Any] | None,
    used: Iterable[Any] | None = None,
    rejected: Iterable[Any] | None = None,
    *,
    used_reason: str = "accepted because it changed the planner decision",
    rejected_reason: str = "rejected because it did not change the planner decision",
    default_reason: str = "reviewed but not selected by planner",
) -> list[dict[str, Any]]:
    """Return a stable decision ledger for navlog move-card candidates.

    Cards in ``used`` are marked as accepted and as decision-changing.
    Cards in ``rejected`` are marked as rejected.  Remaining candidates are
    recorded as skipped so a planner run never silently ignores a card.
    """

    candidate_names = [_card_name(card) for card in candidates or ()]
    used_names = _string_set(used)
    rejected_names = _string_set(rejected)

    for name in sorted(used_names | rejected_names):
        if name not in candidate_names:
            candidate_names.append(name)

    decisions: list[MoveCardDecision] = []
    seen: set[str] = set()

    for name in candidate_names:
        if not name or name in seen:
            continue
        seen.add(name)

        if name in used_names:
            decisions.append(
                MoveCardDecision(
                    card=name,
                    status="used",
                    reason=used_reason,
                    changed_decision=True,
                    evidence=("planner_selected_card",),
                )
            )
        elif name in rejected_names:
            decisions.append(
                MoveCardDecision(
                    card=name,
                    status="rejected",
                    reason=rejected_reason,
                    changed_decision=False,
                    evidence=("planner_rejected_card",),
                )
            )
        else:
            decisions.append(
                MoveCardDecision(
                    card=name,
                    status="skipped",
                    reason=default_reason,
                    changed_decision=False,
                    evidence=("planner_reviewed_card",),
                )
            )

    return [decision.as_dict() for decision in decisions]


def attach_move_card_decisions(
    plan: MutableMapping[str, Any],
    candidates: Iterable[Any] | None,
    used: Iterable[Any] | None = None,
    rejected: Iterable[Any] | None = None,
) -> MutableMapping[str, Any]:
    """Attach the navlog move-card ledger to a planner result mapping."""

    plan[DECISION_LOG_KEY] = build_move_card_decisions(candidates, used, rejected)
    plan["navlog_move_card_acceptance"] = any(
        item["changed_decision"] for item in plan[DECISION_LOG_KEY]
    )
    return plan


def assert_move_card_decisions(plan: Mapping[str, Any]) -> bool:
    """Validate that a planner result explicitly records card decisions."""

    decisions = plan.get(DECISION_LOG_KEY)
    if not isinstance(decisions, list):
        return False
    for item in decisions:
        if not isinstance(item, Mapping):
            return False
        if item.get("status") not in {"used", "rejected", "skipped"}:
            return False
        if "card" not in item or "reason" not in item or "changed_decision" not in item:
            return False
    return True
