"""Replayable first-card failure recordings for onboarding/userlab.

This module keeps the "newcomer got stuck" signal concrete:
- record a first-card attempt as a small deterministic script,
- replay that script without external services,
- emit the smallest repair suggestions that would unblock the attempt.

It is intentionally dependency-light so it can be used from onboarding drills,
userlab acceptance checks, or a plain CLI smoke run.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


Event = Dict[str, Any]
State = Dict[str, Any]
Action = Callable[[State, Mapping[str, Any]], Mapping[str, Any]]


@dataclass
class FirstCardReplay:
    """A replayable recording of an onboarding/userlab first-card attempt."""

    card_id: str
    goal: str
    events: List[Event] = field(default_factory=list)
    fixture: State = field(default_factory=dict)
    schema_version: int = 1

    def add_event(self, kind: str, **data: Any) -> "FirstCardReplay":
        event: Event = {"kind": kind}
        event.update(data)
        self.events.append(event)
        return self

    def to_script(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "card_id": self.card_id,
            "goal": self.goal,
            "fixture": dict(self.fixture),
            "events": list(self.events),
        }

    @classmethod
    def from_script(cls, script: Mapping[str, Any]) -> "FirstCardReplay":
        return cls(
            card_id=str(script.get("card_id", "first-card")),
            goal=str(script.get("goal", "")),
            events=[dict(event) for event in script.get("events", [])],
            fixture=dict(script.get("fixture", {})),
            schema_version=int(script.get("schema_version", 1)),
        )

    def save(self, path: str | Path) -> Path:
        target = Path(path)
        target.write_text(json.dumps(self.to_script(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    @classmethod
    def load(cls, path: str | Path) -> "FirstCardReplay":
        return cls.from_script(json.loads(Path(path).read_text(encoding="utf-8")))


def record_first_card(
    card_id: str,
    goal: str,
    observations: Iterable[Mapping[str, Any]],
    fixture: Optional[Mapping[str, Any]] = None,
) -> FirstCardReplay:
    """Build a deterministic replay script from observed newcomer steps."""

    replay = FirstCardReplay(card_id=card_id, goal=goal, fixture=dict(fixture or {}))
    for index, observation in enumerate(observations):
        event = dict(observation)
        event.setdefault("step", index)
        kind = str(event.pop("kind", event.pop("type", "observe")))
        replay.add_event(kind, **event)
    return replay


def default_actions() -> Dict[str, Action]:
    """Actions understood by the minimal replay engine."""

    def observe(state: State, event: Mapping[str, Any]) -> Mapping[str, Any]:
        note = event.get("note") or event.get("text") or event.get("message")
        if note:
            state.setdefault("notes", []).append(str(note))
        return {"ok": True}

    def click(state: State, event: Mapping[str, Any]) -> Mapping[str, Any]:
        target = str(event.get("target", ""))
        available = set(state.get("available_targets", []))
        ok = not available or target in available
        if ok:
            state["last_target"] = target
        return {"ok": ok, "error": "" if ok else "missing_target", "target": target}

    def input_text(state: State, event: Mapping[str, Any]) -> Mapping[str, Any]:
        field_name = str(event.get("field", "input"))
        text = str(event.get("text", ""))
        required = set(state.get("required_fields", []))
        if field_name in required and not text.strip():
            return {"ok": False, "error": "empty_required_field", "field": field_name}
        state.setdefault("fields", {})[field_name] = text
        return {"ok": True}

    def expect(state: State, event: Mapping[str, Any]) -> Mapping[str, Any]:
        key = str(event.get("key", ""))
        expected = event.get("value", True)
        actual = state.get(key)
        ok = actual == expected
        return {"ok": ok, "error": "" if ok else "expectation_failed", "key": key, "expected": expected, "actual": actual}

    def fail(state: State, event: Mapping[str, Any]) -> Mapping[str, Any]:
        reason = str(event.get("reason", "user_stuck"))
        state["failure_reason"] = reason
        return {"ok": False, "error": reason}

    return {
        "observe": observe,
        "click": click,
        "input": input_text,
        "type": input_text,
        "expect": expect,
        "fail": fail,
    }


def replay_script(
    script: Mapping[str, Any] | FirstCardReplay,
    actions: Optional[Mapping[str, Action]] = None,
) -> Dict[str, Any]:
    """Replay a first-card script and return the first failing step."""

    replay = script if isinstance(script, FirstCardReplay) else FirstCardReplay.from_script(script)
    action_map = dict(default_actions())
    if actions:
        action_map.update(actions)

    state: State = dict(replay.fixture)
    trace: List[Dict[str, Any]] = []
    first_failure: Optional[Dict[str, Any]] = None

    for index, event in enumerate(replay.events):
        kind = str(event.get("kind", "observe"))
        action = action_map.get(kind)
        if action is None:
            result = {"ok": False, "error": "unknown_event", "kind": kind}
        else:
            result = dict(action(state, event))
        row = {"index": index, "kind": kind, "event": dict(event), "result": result}
        trace.append(row)
        if not result.get("ok", False) and first_failure is None:
            first_failure = row
            break

    return {
        "ok": first_failure is None,
        "card_id": replay.card_id,
        "goal": replay.goal,
        "state": state,
        "trace": trace,
        "first_failure": first_failure,
        "suggestions": suggest_minimal_repairs(replay, first_failure, state),
    }


def suggest_minimal_repairs(
    replay: FirstCardReplay,
    failure: Optional[Mapping[str, Any]],
    state: Optional[Mapping[str, Any]] = None,
) -> List[str]:
    """Generate small, concrete repair suggestions from the replay failure."""

    if failure is None:
        return []

    result = dict(failure.get("result", {}))
    event = dict(failure.get("event", {}))
    error = str(result.get("error", ""))

    if error == "missing_target":
        target = result.get("target") or event.get("target") or "the clicked control"
        return [
            f"Expose or rename the first-card control `{target}` so the recorded click can find it.",
            "Add a visible fallback hint before this click, not a new multi-step flow.",
        ]

    if error == "empty_required_field":
        field_name = result.get("field") or event.get("field") or "required field"
        return [
            f"Pre-fill, validate inline, or label `{field_name}` before submit.",
            "Keep the repair local to the first card; do not add an extra onboarding screen.",
        ]

    if error == "expectation_failed":
        key = result.get("key") or event.get("key") or "expected state"
        expected = result.get("expected")
        actual = result.get("actual")
        return [
            f"Make `{key}` become {expected!r} during the first-card path; replay saw {actual!r}.",
            "Add one regression replay using this script after the fix.",
        ]

    if error == "unknown_event":
        kind = result.get("kind") or event.get("kind") or "event"
        return [
            f"Teach the replay harness the `{kind}` event or record it as observe/click/input/expect.",
        ]

    reason = error or str(event.get("reason", "user_stuck"))
    notes = list((state or {}).get("notes", []))
    context = f" Last note: {notes[-1]}" if notes else ""
    return [
        f"Remove the first-card blocker `{reason}` with the smallest UI copy or default-state change.{context}",
        "Re-run this exact script and require the first failure to disappear.",
    ]


def summarize_replay(report: Mapping[str, Any]) -> str:
    """Return a compact human-readable replay summary."""

    status = "PASS" if report.get("ok") else "FAIL"
    head = f"{status} {report.get('card_id', 'first-card')}: {report.get('goal', '')}".rstrip()
    failure = report.get("first_failure")
    if not failure:
        return head
    result = failure.get("result", {})
    suggestions = report.get("suggestions", [])
    first = suggestions[0] if suggestions else "No suggestion generated."
    return f"{head}\nstep {failure.get('index')} {failure.get('kind')} failed: {result.get('error')}\nfix: {first}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Replay onboarding/userlab first-card failure scripts.")
    parser.add_argument("script", help="Path to a recorded first-card replay JSON script.")
    args = parser.parse_args(argv)

    replay = FirstCardReplay.load(args.script)
    report = replay_script(replay)
    print(summarize_replay(report))
    for suggestion in report.get("suggestions", [])[1:]:
        print(f"- {suggestion}")
    return 0 if report.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
