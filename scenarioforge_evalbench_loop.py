"""Bridge real field observations from scenarioforge into evalbench golden tasks.

This module is intentionally dependency-light: it can be imported by either
``scenarioforge`` or ``evalbench`` without creating a hard coupling.  The first
golden task captures a real observed failure mode for this codebase: patch
responses sometimes drift into Markdown fences, JSON, or explanatory prose even
when the hand protocol requires plain NOTE/EDIT/WRITE blocks only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional


@dataclass(frozen=True)
class GoldenTask:
    """A small evalbench-compatible task distilled from field feedback."""

    task_id: str
    source: str
    observation: str
    prompt: str
    expectation: str
    grader_name: str
    tags: tuple[str, ...] = ()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "id": self.task_id,
            "task_id": self.task_id,
            "source": self.source,
            "observation": self.observation,
            "prompt": self.prompt,
            "expectation": self.expectation,
            "grader": self.grader_name,
            "tags": list(self.tags),
        }


EXTERNAL_OBSERVATION = (
    "When asked to emit repository patches, assistants may wrap the answer in "
    "Markdown fences, JSON, or extra explanation, causing the hand/applier to "
    "skip otherwise valid changes."
)

PATCH_PROTOCOL_GOLDEN = GoldenTask(
    task_id="scenarioforge.field.patch_protocol_plaintext.v1",
    source="scenarioforge→evalbench real-feedback loop",
    observation=EXTERNAL_OBSERVATION,
    prompt=(
        "You are the repository hand. Output a tiny Python code change using only "
        "the accepted patch protocol: first a NOTE line, then one WRITE or EDIT "
        "block. Do not use Markdown fences, JSON, or explanatory prose."
    ),
    expectation=(
        "The answer is plain text beginning with NOTE:, contains at least one "
        "<<<WRITE path=...>>> or <<<EDIT path=...>>> block closed by <<<END>>>, "
        "and contains no Markdown code fence or JSON envelope."
    ),
    grader_name="grade_patch_protocol_plaintext",
    tags=("golden", "field-feedback", "scenarioforge", "evalbench", "format"),
)


def grade_patch_protocol_plaintext(answer: Any) -> Dict[str, Any]:
    """Grade whether an answer obeys the hand patch protocol.

    The grader returns a conventional dictionary so it is easy for evalbench
    adapters to consume even if they do not share a task class with this module.
    """

    text = "" if answer is None else str(answer)
    stripped = text.strip()
    failures: List[str] = []

    if not stripped.startswith("NOTE:"):
        failures.append("missing leading NOTE line")
    if "```" in stripped:
        failures.append("contains Markdown code fence")
    if stripped.startswith("{") or stripped.startswith("["):
        failures.append("looks like JSON instead of patch protocol")
    has_block = "<<<WRITE path=" in stripped or "<<<EDIT path=" in stripped
    if not has_block:
        failures.append("missing WRITE or EDIT block")
    if "<<<END>>>" not in stripped:
        failures.append("missing block terminator")
    if "---OLD---" in stripped and "---NEW---" not in stripped:
        failures.append("EDIT block missing NEW section")

    score = 1.0 if not failures else 0.0
    return {
        "score": score,
        "passed": score == 1.0,
        "failures": failures,
        "task_id": PATCH_PROTOCOL_GOLDEN.task_id,
    }


GRADERS: Dict[str, Callable[[Any], Dict[str, Any]]] = {
    PATCH_PROTOCOL_GOLDEN.grader_name: grade_patch_protocol_plaintext,
}

GOLDEN_TASKS: tuple[GoldenTask, ...] = (PATCH_PROTOCOL_GOLDEN,)


def iter_evalbench_tasks() -> Iterable[Dict[str, Any]]:
    """Yield evalbench-friendly task dictionaries."""

    for task in GOLDEN_TASKS:
        payload = task.as_dict()
        payload["grade"] = GRADERS[task.grader_name]
        yield payload


def register(evalbench: Any) -> int:
    """Best-effort registration hook for evalbench-style registries.

    Supported registry shapes are deliberately broad:
    * object.register_task(task)
    * object.add_task(task)
    * object.tasks list
    * dict with a ``tasks`` list

    Returns the number of tasks inserted.
    """

    inserted = 0
    for task in iter_evalbench_tasks():
        if hasattr(evalbench, "register_task"):
            evalbench.register_task(task)
            inserted += 1
        elif hasattr(evalbench, "add_task"):
            evalbench.add_task(task)
            inserted += 1
        elif hasattr(evalbench, "tasks") and isinstance(evalbench.tasks, list):
            evalbench.tasks.append(task)
            inserted += 1
        elif isinstance(evalbench, dict):
            tasks = evalbench.setdefault("tasks", [])
            if isinstance(tasks, list):
                tasks.append(task)
                inserted += 1
    return inserted


def forge_from_observation(observation: Optional[str] = None) -> Mapping[str, Any]:
    """Return the golden task forged from a field observation.

    ``observation`` is accepted for future scenarioforge callers; the current
    canonical benchmark remains stable so score history is comparable.
    """

    task = PATCH_PROTOCOL_GOLDEN.as_dict()
    if observation:
        task["input_observation"] = observation
    task["grade"] = grade_patch_protocol_plaintext
    return task
