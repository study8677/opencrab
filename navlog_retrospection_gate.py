"""Old navigation-log rumination gate.

This module samples historical navigation logs, detects stale or conflicting
move cards, and emits a compact three-item revalidation/retirement checklist.
It is intentionally dependency-light so it can be used from drills, tests, or
manual review scripts without touching external services.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import hashlib
from typing import Iterable, List, Mapping, Optional, Sequence


DEFAULT_SAMPLE_SIZE = 1139
STALE_AFTER_DAYS = 180
CONFLICT_WORDS = (
    "conflict",
    "contradict",
    "inconsistent",
    "regression",
    "broke",
    "rollback",
    "失效",
    "冲突",
    "矛盾",
    "回滚",
    "过期",
)
SUCCESS_WORDS = (
    "validated",
    "graduated",
    "accepted",
    "passed",
    "success",
    "有效",
    "通过",
    "采纳",
)


@dataclass(frozen=True)
class NavlogCardFinding:
    """A suspected stale or conflicting move-card finding."""

    card: str
    reason: str
    evidence_count: int
    latest_seen: Optional[str] = None
    action: str = "revalidate"


def _stable_bucket(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()
    return int(digest[:16], 16)


def sample_navlogs(
    logs: Iterable[Mapping[str, object]],
    sample_size: int = DEFAULT_SAMPLE_SIZE,
) -> List[Mapping[str, object]]:
    """Return a deterministic pseudo-random sample of navigation logs.

    The sampling key is content-derived, so repeated runs over the same corpus
    produce the same review set without requiring global randomness.
    """

    if sample_size <= 0:
        return []
    keyed = []
    for index, log in enumerate(logs):
        key_text = "%s|%s|%s" % (
            log.get("id", index),
            log.get("date", ""),
            log.get("text", log.get("summary", "")),
        )
        keyed.append((_stable_bucket(key_text), index, log))
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [item[2] for item in keyed[:sample_size]]


def _parse_date(value: object) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str) or not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value[:19], fmt).date()
        except ValueError:
            continue
    return None


def _card_name(log: Mapping[str, object]) -> str:
    for key in ("card", "move_card", "move", "skill", "title"):
        value = log.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return "unknown-card"


def _log_text(log: Mapping[str, object]) -> str:
    parts = []
    for key in ("text", "summary", "decision", "outcome", "notes"):
        value = log.get(key)
        if isinstance(value, str):
            parts.append(value)
    return "\n".join(parts).lower()


def find_stale_or_conflicting_cards(
    logs: Iterable[Mapping[str, object]],
    today: Optional[date] = None,
    stale_after_days: int = STALE_AFTER_DAYS,
) -> List[NavlogCardFinding]:
    """Detect move cards whose old evidence may mislead current planning."""

    today = today or date.today()
    grouped = {}
    for log in logs:
        card = _card_name(log)
        grouped.setdefault(card, []).append(log)

    findings: List[NavlogCardFinding] = []
    for card, card_logs in grouped.items():
        texts = [_log_text(log) for log in card_logs]
        conflict_hits = sum(
            1 for text in texts if any(word in text for word in CONFLICT_WORDS)
        )
        success_hits = sum(
            1 for text in texts if any(word in text for word in SUCCESS_WORDS)
        )

        parsed_dates = [_parse_date(log.get("date")) for log in card_logs]
        known_dates = [value for value in parsed_dates if value is not None]
        latest = max(known_dates) if known_dates else None
        age_days = (today - latest).days if latest else None

        if conflict_hits and success_hits:
            findings.append(
                NavlogCardFinding(
                    card=card,
                    reason="conflicting success and failure evidence in old logs",
                    evidence_count=conflict_hits + success_hits,
                    latest_seen=latest.isoformat() if latest else None,
                    action="revalidate",
                )
            )
        elif conflict_hits:
            findings.append(
                NavlogCardFinding(
                    card=card,
                    reason="conflict or rollback language found in log evidence",
                    evidence_count=conflict_hits,
                    latest_seen=latest.isoformat() if latest else None,
                    action="retire",
                )
            )
        elif age_days is not None and age_days > stale_after_days:
            findings.append(
                NavlogCardFinding(
                    card=card,
                    reason="last supporting evidence is older than %s days" % stale_after_days,
                    evidence_count=len(card_logs),
                    latest_seen=latest.isoformat(),
                    action="revalidate",
                )
            )

    findings.sort(
        key=lambda item: (
            0 if item.action == "retire" else 1,
            -item.evidence_count,
            item.card,
        )
    )
    return findings


def build_review_checklist(
    findings: Sequence[NavlogCardFinding],
    limit: int = 3,
) -> List[str]:
    """Build exactly the top review/retirement checklist lines available."""

    checklist = []
    for finding in findings[: max(0, limit)]:
        when = finding.latest_seen or "unknown-date"
        checklist.append(
            "[%s] %s — %s; evidence=%s; latest=%s"
            % (
                finding.action,
                finding.card,
                finding.reason,
                finding.evidence_count,
                when,
            )
        )
    return checklist


def rumination_gate(
    logs: Iterable[Mapping[str, object]],
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    today: Optional[date] = None,
) -> List[str]:
    """Sample old logs and emit three revalidation/retirement checklist items."""

    sampled = sample_navlogs(logs, sample_size=sample_size)
    findings = find_stale_or_conflicting_cards(sampled, today=today)
    return build_review_checklist(findings, limit=3)


__all__ = [
    "DEFAULT_SAMPLE_SIZE",
    "NavlogCardFinding",
    "build_review_checklist",
    "find_stale_or_conflicting_cards",
    "rumination_gate",
    "sample_navlogs",
]
