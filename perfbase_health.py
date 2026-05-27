"""Perf baseline health adapter.

This module turns key-command performance baselines into a small, uniform
health-check result.  It is intentionally dependency-light so it can be
imported by health/checkup/release gates without pulling in benchmarking code.

Accepted baseline JSON shapes are deliberately forgiving:

1. Mapping by command::

    {
      "crab plan": {"baseline_ms": 120.0, "current_ms": 155.0, "threshold_pct": 20}
    }

2. List of records::

    [
      {"command": "crab plan", "baseline_ms": 120.0, "current_ms": 155.0}
    ]

3. perfbase-style aliases are also accepted: ``p50_ms``, ``elapsed_ms``,
   ``mean_ms``, ``latest_ms``, ``allowed_regression_pct``.

The check is RED when any critical command regresses beyond its threshold.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


DEFAULT_THRESHOLD_PCT = 20.0
DEFAULT_BASELINE_PATHS: Tuple[str, ...] = (
    ".crab/perfbase.json",
    ".crab/perf_baseline.json",
    "perfbase.json",
)


@dataclass(frozen=True)
class PerfHealthFinding:
    command: str
    baseline_ms: float
    current_ms: float
    regression_pct: float
    threshold_pct: float
    status: str
    advice: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "command": self.command,
            "baseline_ms": self.baseline_ms,
            "current_ms": self.current_ms,
            "regression_pct": self.regression_pct,
            "threshold_pct": self.threshold_pct,
            "status": self.status,
            "advice": self.advice,
        }


def _first_number(record: Mapping[str, Any], names: Sequence[str]) -> Optional[float]:
    for name in names:
        value = record.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                continue
    return None


def _normalise_records(payload: Any) -> List[Mapping[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, Mapping)]

    if not isinstance(payload, Mapping):
        return []

    for key in ("commands", "results", "benchmarks", "perfbase"):
        nested = payload.get(key)
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, Mapping)]
        if isinstance(nested, Mapping):
            return _normalise_records(nested)

    records: List[Mapping[str, Any]] = []
    for command, value in payload.items():
        if isinstance(value, Mapping):
            merged = dict(value)
            merged.setdefault("command", str(command))
            records.append(merged)
    return records


def load_baseline(path: Optional[str] = None) -> Tuple[Optional[str], Any]:
    """Load a baseline payload.

    Returns ``(used_path, payload)``.  If no file exists, both values are
    ``(None, None)`` so callers can report a neutral health result.
    """

    paths: Iterable[str]
    if path:
        paths = (path,)
    else:
        paths = DEFAULT_BASELINE_PATHS

    for candidate in paths:
        if os.path.exists(candidate):
            with open(candidate, "r", encoding="utf-8") as handle:
                return candidate, json.load(handle)
    return None, None


def evaluate_payload(
    payload: Any,
    *,
    default_threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    critical_commands: Optional[Iterable[str]] = None,
) -> List[PerfHealthFinding]:
    """Evaluate a perfbase payload and return per-command findings."""

    critical = set(critical_commands or ())
    findings: List[PerfHealthFinding] = []

    for record in _normalise_records(payload):
        command = str(record.get("command") or record.get("name") or record.get("cmd") or "").strip()
        if not command:
            continue
        if critical and command not in critical:
            continue

        baseline_ms = _first_number(
            record,
            ("baseline_ms", "base_ms", "previous_ms", "golden_ms", "p50_baseline_ms"),
        )
        current_ms = _first_number(
            record,
            ("current_ms", "latest_ms", "elapsed_ms", "mean_ms", "p50_ms", "duration_ms"),
        )
        if baseline_ms is None or current_ms is None or baseline_ms <= 0:
            continue

        threshold_pct = _first_number(
            record,
            ("threshold_pct", "allowed_regression_pct", "max_regression_pct"),
        )
        if threshold_pct is None:
            threshold_pct = float(default_threshold_pct)

        regression_pct = ((current_ms - baseline_ms) / baseline_ms) * 100.0
        is_red = regression_pct > threshold_pct
        status = "red" if is_red else "green"
        advice = (
            "performance regression exceeds baseline; rollback or revert the recent hot-path change"
            if is_red
            else "within performance baseline"
        )
        findings.append(
            PerfHealthFinding(
                command=command,
                baseline_ms=round(baseline_ms, 3),
                current_ms=round(current_ms, 3),
                regression_pct=round(regression_pct, 3),
                threshold_pct=round(float(threshold_pct), 3),
                status=status,
                advice=advice,
            )
        )

    return findings


def check_perfbase_health(
    path: Optional[str] = None,
    *,
    default_threshold_pct: float = DEFAULT_THRESHOLD_PCT,
    critical_commands: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Return a uniform health-check dictionary for perf baselines."""

    used_path, payload = load_baseline(path)
    if payload is None:
        return {
            "name": "perfbase",
            "status": "unknown",
            "ok": True,
            "summary": "no perf baseline file found",
            "advice": "run perfbase for key commands before release gating",
            "path": used_path,
            "findings": [],
        }

    findings = evaluate_payload(
        payload,
        default_threshold_pct=default_threshold_pct,
        critical_commands=critical_commands,
    )
    red = [finding for finding in findings if finding.status == "red"]
    status = "red" if red else "green"

    return {
        "name": "perfbase",
        "status": status,
        "ok": not red,
        "summary": (
            f"{len(red)} command(s) exceed perf baseline; rollback recommended"
            if red
            else f"{len(findings)} command(s) within perf baseline"
        ),
        "advice": (
            "rollback or revert the latest change before shipping"
            if red
            else "keep monitoring perfbase on critical commands"
        ),
        "path": used_path,
        "findings": [finding.as_dict() for finding in findings],
    }


def check(path: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    """Compatibility alias for health aggregators that call ``check()``."""

    return check_perfbase_health(path, **kwargs)


def healthcheck(path: Optional[str] = None, **kwargs: Any) -> Dict[str, Any]:
    """Compatibility alias for health aggregators that call ``healthcheck()``."""

    return check_perfbase_health(path, **kwargs)


def register(registry: Any) -> bool:
    """Best-effort registration hook for simple health registries.

    Supports registries exposing ``register(name, callable)``, dict-like
    registries, or list-like registries.  Returns whether registration worked.
    """

    if hasattr(registry, "register"):
        registry.register("perfbase", check_perfbase_health)
        return True
    if isinstance(registry, dict):
        registry["perfbase"] = check_perfbase_health
        return True
    if hasattr(registry, "append"):
        registry.append(("perfbase", check_perfbase_health))
        return True
    return False


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(argv or [])
    path = args[0] if args else None
    result = check_perfbase_health(path)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if result.get("status") == "red" else 0


if __name__ == "__main__":
    raise SystemExit(main())
