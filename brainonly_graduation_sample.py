"""Pure helpers for judging brain-only end-to-end graduation samples.

The functions in this module are intentionally side-effect free so they can be
used by drills, regressions, and review scripts without touching the filesystem
or invoking external tools.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Tuple


REQUIRED_PHASES: Tuple[str, ...] = ("generate", "fit", "validate", "backfill")
FORBIDDEN_TOOLS: Tuple[str, ...] = ("claude",)


def _clean_token(value: Any) -> str:
    """Return a normalized lowercase token for comparisons."""
    return str(value or "").strip().lower()


def brainonly_graduation_report(
    events: Iterable[Mapping[str, Any]],
    *,
    required_phases: Iterable[str] = REQUIRED_PHASES,
    forbidden_tools: Iterable[str] = FORBIDDEN_TOOLS,
) -> Dict[str, Any]:
    """Summarize whether an end-to-end sample satisfies brain-only graduation.

    Each event may contain:
      - phase: one of generate / fit / validate / backfill
      - tool: the actor/tool used for that phase
      - benefit: numeric benefit contribution; positive total is required

    The returned dict is deterministic and contains only plain data, making it
    safe to serialize or compare in regression tests.
    """

    required = tuple(_clean_token(phase) for phase in required_phases)
    forbidden = tuple(_clean_token(tool) for tool in forbidden_tools)

    seen_phases = set()
    forbidden_hits = []
    benefit_total = 0.0
    event_count = 0

    for event in events:
        event_count += 1
        phase = _clean_token(event.get("phase"))
        tool = _clean_token(event.get("tool"))

        if phase:
            seen_phases.add(phase)

        if tool and tool in forbidden:
            forbidden_hits.append(tool)

        try:
            benefit_total += float(event.get("benefit", 0) or 0)
        except (TypeError, ValueError):
            pass

    missing_phases = tuple(phase for phase in required if phase not in seen_phases)
    passed = bool(event_count) and not missing_phases and not forbidden_hits and benefit_total > 0

    return {
        "passed": passed,
        "event_count": event_count,
        "missing_phases": missing_phases,
        "forbidden_tools": tuple(forbidden_hits),
        "benefit_total": benefit_total,
    }


def is_brainonly_graduation_sample(events: Iterable[Mapping[str, Any]]) -> bool:
    """Return True when events form a complete positive brain-only sample."""
    return bool(brainonly_graduation_report(events)["passed"])
