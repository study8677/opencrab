"""Small self-modification friction review helpers.

This module is intentionally dependency-light: callers may feed it records
already produced by throughput.py/bottleneck.py, but it also accepts plain dicts.
It reviews the most recent self-modification attempts, identifies the stage that
consumed the most time, and applies one conservative "friction surgery" knob to
a config dict so repeated work is reduced without changing safety semantics.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


_DURATION_KEYS = ("duration_s", "seconds", "elapsed_s", "elapsed", "cost_s", "cost")
_STAGE_KEYS = ("stage", "phase", "step", "bottleneck", "kind", "name")
_SAFE_FIX_BY_STAGE = {
    "read": ("reuse_recent_file_snapshot", True),
    "scan": ("reuse_recent_file_snapshot", True),
    "locate": ("reuse_recent_file_snapshot", True),
    "plan": ("prefer_small_unique_edit", True),
    "edit": ("prefer_small_unique_edit", True),
    "patch": ("prefer_small_unique_edit", True),
    "compile": ("run_compile_once_after_batch", True),
    "py_compile": ("run_compile_once_after_batch", True),
    "import": ("run_single_import_probe_after_compile", True),
    "regression": ("run_targeted_regression_first", True),
    "test": ("run_targeted_regression_first", True),
}


@dataclass(frozen=True)
class FrictionEvent:
    """Normalized self-modification timing record."""

    stage: str
    duration_s: float
    label: str = ""


def _float_or_none(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip()
        if text.endswith("ms"):
            try:
                return float(text[:-2].strip()) / 1000.0
            except ValueError:
                return None
        if text.endswith("s"):
            text = text[:-1].strip()
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _first_text(record: Mapping[str, Any], keys: Tuple[str, ...], default: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def normalize_event(record: Mapping[str, Any]) -> Optional[FrictionEvent]:
    """Convert a throughput/bottleneck/plain mapping into a FrictionEvent.

    Unknown or non-positive durations are ignored because they cannot identify
    the highest time sink reliably.
    """

    duration = None
    for key in _DURATION_KEYS:
        if key in record:
            duration = _float_or_none(record.get(key))
            if duration is not None:
                break
    if duration is None or duration < 0:
        return None

    stage = _first_text(record, _STAGE_KEYS, "unknown").lower()
    label = _first_text(record, ("label", "title", "file", "path", "id"), "")
    return FrictionEvent(stage=stage, duration_s=duration, label=label)


def review_recent_selfmods(
    records: Iterable[Mapping[str, Any]], limit: int = 10
) -> Dict[str, Any]:
    """Review the most recent self-modification records.

    Returns a compact dict with throughput and bottleneck views:
    - throughput: count, total seconds, median seconds
    - bottleneck: stage with highest cumulative time, its total, and share
    """

    if limit <= 0:
        limit = 10

    normalized: List[FrictionEvent] = []
    for record in records:
        event = normalize_event(record)
        if event is not None:
            normalized.append(event)

    recent = normalized[-limit:]
    durations = [event.duration_s for event in recent]
    total = sum(durations)

    by_stage: Dict[str, float] = {}
    counts: Dict[str, int] = {}
    for event in recent:
        by_stage[event.stage] = by_stage.get(event.stage, 0.0) + event.duration_s
        counts[event.stage] = counts.get(event.stage, 0) + 1

    if by_stage:
        bottleneck_stage, bottleneck_seconds = max(
            by_stage.items(), key=lambda item: (item[1], item[0])
        )
    else:
        bottleneck_stage, bottleneck_seconds = "none", 0.0

    culprit = None
    if recent:
        culprit_event = max(recent, key=lambda event: event.duration_s)
        culprit = {
            "stage": culprit_event.stage,
            "duration_s": round(culprit_event.duration_s, 6),
            "label": culprit_event.label,
        }

    return {
        "window": len(recent),
        "throughput": {
            "count": len(recent),
            "total_s": round(total, 6),
            "median_s": round(median(durations), 6) if durations else 0.0,
        },
        "bottleneck": {
            "stage": bottleneck_stage,
            "total_s": round(bottleneck_seconds, 6),
            "share": round((bottleneck_seconds / total), 6) if total else 0.0,
            "count": counts.get(bottleneck_stage, 0),
            "culprit": culprit,
        },
        "stage_totals": {stage: round(seconds, 6) for stage, seconds in sorted(by_stage.items())},
    }


def choose_micro_fix(summary: Mapping[str, Any]) -> Dict[str, Any]:
    """Choose one conservative friction-reduction knob for the bottleneck stage."""

    bottleneck = summary.get("bottleneck")
    stage = ""
    if isinstance(bottleneck, Mapping):
        stage = str(bottleneck.get("stage", "")).lower()

    key_value = _SAFE_FIX_BY_STAGE.get(stage)
    if key_value is None:
        key_value = ("prefer_small_unique_edit", True)

    key, value = key_value
    return {
        "bottleneck_stage": stage or "unknown",
        "config_key": key,
        "config_value": value,
        "reason": "highest cumulative time in recent self-modification window",
    }


def apply_micro_fix(
    config: Optional[Mapping[str, Any]], summary: Mapping[str, Any]
) -> Dict[str, Any]:
    """Return a new config dict with the selected friction surgery applied."""

    updated = dict(config or {})
    fix = choose_micro_fix(summary)
    updated[str(fix["config_key"])] = fix["config_value"]
    updated["last_friction_surgery"] = fix
    return updated


def friction_surgery(
    records: Iterable[Mapping[str, Any]],
    config: Optional[Mapping[str, Any]] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """Review recent records and apply exactly one low-risk friction fix."""

    summary = review_recent_selfmods(records, limit=limit)
    return {
        "summary": summary,
        "fix": choose_micro_fix(summary),
        "config": apply_micro_fix(config, summary),
    }


def regression_selftest() -> bool:
    """Minimal regression proof for the surgery loop."""

    records = [
        {"stage": "read", "duration_s": 1.0},
        {"stage": "compile", "duration_s": 2.0},
        {"stage": "compile", "duration_s": 3.0},
        {"stage": "test", "duration_s": 0.5},
    ]
    result = friction_surgery(records, config={"existing": True})
    assert result["summary"]["window"] == 4
    assert result["summary"]["bottleneck"]["stage"] == "compile"
    assert result["fix"]["config_key"] == "run_compile_once_after_batch"
    assert result["config"]["run_compile_once_after_batch"] is True
    assert result["config"]["existing"] is True
    return True


if __name__ == "__main__":
    regression_selftest()
