"""External-helper cooldown for forcing a brain-only fitting after Claude use.

The rule is intentionally simple:

* When a Claude/external-helper call is recorded for a task family, that family
  becomes frozen.
* The next same-family task should be routed through a brain-only fit room first.
* Recording that brain-only fitting clears the freeze.

This module is dependency-light and safe to import from hot paths.  State is
persisted as JSON so the cooldown survives process restarts.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Mapping, MutableMapping, Optional


DEFAULT_STATE_PATH = ".crab_external_cooldown.json"
STATE_ENV = "CRAB_EXTERNAL_COOLDOWN_STATE"


TASK_KIND_KEYWORDS = {
    "patch": ("patch", "edit", "rewrite", "diff", "modify", "fix", "code"),
    "test": ("test", "regression", "pytest", "compile", "smoke"),
    "design": ("design", "plan", "architecture", "proposal", "strategy"),
    "debug": ("debug", "trace", "error", "failure", "exception", "bug"),
    "review": ("review", "audit", "inspect", "critique", "check"),
    "docs": ("doc", "readme", "explain", "manual", "guide"),
}


@dataclass(frozen=True)
class CooldownDecision:
    """Decision returned before routing a task."""

    task_kind: str
    brain_only_required: bool
    reason: str = ""

    @property
    def route(self) -> str:
        return "brain-only-fitroom" if self.brain_only_required else "normal"


def _state_path(path: Optional[os.PathLike[str] | str] = None) -> Path:
    if path is not None:
        return Path(path)
    return Path(os.environ.get(STATE_ENV, DEFAULT_STATE_PATH))


def classify_task(task: Any) -> str:
    """Map a task description to a stable broad family.

    Callers may pass an explicit mapping with ``kind`` or ``task_kind``.  For
    plain strings we use conservative keyword buckets; unknown work falls into
    ``general`` so repeated external use still creates pressure.
    """

    if isinstance(task, Mapping):
        explicit = task.get("task_kind") or task.get("kind") or task.get("type")
        if explicit:
            return str(explicit).strip().lower() or "general"
        text = " ".join(str(v) for v in task.values())
    else:
        text = str(task)

    lowered = text.lower()
    for kind, keywords in TASK_KIND_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return kind
    return "general"


def _empty_state() -> Dict[str, Any]:
    return {"version": 1, "frozen": {}, "events": []}


def load_state(path: Optional[os.PathLike[str] | str] = None) -> Dict[str, Any]:
    target = _state_path(path)
    if not target.exists():
        return _empty_state()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state()
    if not isinstance(data, dict):
        return _empty_state()
    data.setdefault("version", 1)
    data.setdefault("frozen", {})
    data.setdefault("events", [])
    if not isinstance(data["frozen"], dict):
        data["frozen"] = {}
    if not isinstance(data["events"], list):
        data["events"] = []
    return data


def save_state(state: Mapping[str, Any], path: Optional[os.PathLike[str] | str] = None) -> None:
    target = _state_path(path)
    parent = target.parent
    if str(parent):
        parent.mkdir(parents=True, exist_ok=True)

    payload = json.dumps(state, ensure_ascii=False, sort_keys=True, indent=2)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", dir=str(parent or Path(".")))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
        os.replace(tmp_name, target)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _append_event(state: MutableMapping[str, Any], event: Mapping[str, Any]) -> None:
    events = state.setdefault("events", [])
    if not isinstance(events, list):
        events = []
        state["events"] = events
    stamped = {"ts": time.time(), **dict(event)}
    events.append(stamped)
    del events[:-100]


def record_claude_call(
    task: Any,
    *,
    provider: str = "claude",
    path: Optional[os.PathLike[str] | str] = None,
    metadata: Optional[Mapping[str, Any]] = None,
) -> str:
    """Freeze the task family after an external Claude call.

    Returns the classified task kind.
    """

    kind = classify_task(task)
    state = load_state(path)
    frozen = state.setdefault("frozen", {})
    frozen[kind] = {
        "provider": provider,
        "since": time.time(),
        "requires": "brain-only-fitroom",
        "task": str(task)[:500],
        "metadata": dict(metadata or {}),
    }
    _append_event(
        state,
        {
            "event": "external_call_recorded",
            "provider": provider,
            "task_kind": kind,
        },
    )
    save_state(state, path)
    return kind


def decision_for(task: Any, *, path: Optional[os.PathLike[str] | str] = None) -> CooldownDecision:
    """Return whether this task must first go through brain-only fitting."""

    kind = classify_task(task)
    state = load_state(path)
    frozen = state.get("frozen", {})
    if isinstance(frozen, Mapping) and kind in frozen:
        provider = frozen.get(kind, {}).get("provider", "external") if isinstance(frozen.get(kind), Mapping) else "external"
        return CooldownDecision(
            task_kind=kind,
            brain_only_required=True,
            reason=f"{kind} is frozen after {provider}; run brain-only fit room first",
        )
    return CooldownDecision(task_kind=kind, brain_only_required=False)


def brain_only_required(task: Any, *, path: Optional[os.PathLike[str] | str] = None) -> bool:
    return decision_for(task, path=path).brain_only_required


def record_brain_only_fit(
    task: Any,
    *,
    path: Optional[os.PathLike[str] | str] = None,
    outcome: str = "attempted",
    metadata: Optional[Mapping[str, Any]] = None,
) -> bool:
    """Record the mandatory brain-only fitting and clear a matching freeze.

    Returns True when a freeze was cleared.
    """

    kind = classify_task(task)
    state = load_state(path)
    frozen = state.setdefault("frozen", {})
    cleared = isinstance(frozen, MutableMapping) and kind in frozen
    if cleared:
        del frozen[kind]
    _append_event(
        state,
        {
            "event": "brain_only_fit_recorded",
            "task_kind": kind,
            "outcome": outcome,
            "cleared_freeze": cleared,
            "metadata": dict(metadata or {}),
        },
    )
    save_state(state, path)
    return bool(cleared)


def assert_brain_only_allowed(task: Any, *, path: Optional[os.PathLike[str] | str] = None) -> None:
    """Raise if a same-family external route is attempted during cooldown."""

    decision = decision_for(task, path=path)
    if decision.brain_only_required:
        raise RuntimeError(decision.reason)


__all__ = [
    "CooldownDecision",
    "assert_brain_only_allowed",
    "brain_only_required",
    "classify_task",
    "decision_for",
    "load_state",
    "record_brain_only_fit",
    "record_claude_call",
    "save_state",
]
