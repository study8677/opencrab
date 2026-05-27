"""Anti-cheat layers for hot evalbench golden tasks.

This module keeps a small, explicit registry of value-oriented checks for
high-heat golden tasks.  The fields are intentionally plain data so evalbench,
audit tools, or release notes can consume them without importing heavy code.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, MutableMapping, Optional


@dataclass(frozen=True)
class FailureExample:
    """A concrete way a benchmark can look good while being useless."""

    name: str
    symptom: str
    why_it_is_bad: str


@dataclass(frozen=True)
class AntiCheatLayer:
    """Value proof metadata for a golden eval task."""

    task_id: str
    title: str
    beneficiaries: List[str]
    counter_metrics: List[str]
    failure_examples: List[FailureExample]

    def as_dict(self) -> Dict[str, object]:
        """Return a JSON-serialisable representation."""

        return {
            "task_id": self.task_id,
            "title": self.title,
            "beneficiaries": list(self.beneficiaries),
            "counter_metrics": list(self.counter_metrics),
            "failure_examples": [
                {
                    "name": example.name,
                    "symptom": example.symptom,
                    "why_it_is_bad": example.why_it_is_bad,
                }
                for example in self.failure_examples
            ],
        }


HOT_GOLDEN_ANTI_CHEAT_LAYERS: Dict[str, AntiCheatLayer] = {
    "golden.patch_compiles_and_imports": AntiCheatLayer(
        task_id="golden.patch_compiles_and_imports",
        title="Patch keeps Python syntax valid and crab importable",
        beneficiaries=[
            "maintainers who need every accepted patch to be runnable",
            "downstream automation that imports crab before executing drills",
            "future agents relying on a non-broken codebase for self-repair",
        ],
        counter_metrics=[
            "reject score gains if py_compile or import smoke is skipped",
            "track number of files touched without corresponding import safety",
            "penalise patches that only add inert data while avoiding exercised code",
        ],
        failure_examples=[
            FailureExample(
                name="dead-file score padding",
                symptom="the benchmark passes because a new module is syntactically valid but nothing imports or uses it",
                why_it_is_bad="the score rises without reducing the risk that core crab import paths are broken",
            ),
            FailureExample(
                name="compile-only tunnel vision",
                symptom="py_compile succeeds while import-time side effects crash in normal use",
                why_it_is_bad="users experience failure even though the golden task reports success",
            ),
        ],
    ),
    "golden.evidence_backed_value_claim": AntiCheatLayer(
        task_id="golden.evidence_backed_value_claim",
        title="Value claims are tied to evidence instead of benchmark wording",
        beneficiaries=[
            "reviewers deciding whether a patch produced real user value",
            "operators comparing claimed benefits against observed outcomes",
            "product owners who need audit trails for high-confidence releases",
        ],
        counter_metrics=[
            "flag claims that restate the prompt without naming observable evidence",
            "measure ratio of value claims to concrete artifacts or test outcomes",
            "penalise vague improvement language that lacks a beneficiary",
        ],
        failure_examples=[
            FailureExample(
                name="prompt parroting",
                symptom="the answer says it improves evalbench because the task asked for evalbench improvement",
                why_it_is_bad="the patch optimises for agreement with the prompt rather than verifiable usefulness",
            ),
            FailureExample(
                name="metric without witness",
                symptom="a higher score is reported but no beneficiary, trace, or failure mode is attached",
                why_it_is_bad="reviewers cannot tell whether the score corresponds to user-visible progress",
            ),
        ],
    ),
    "golden.rollback_and_failure_learning": AntiCheatLayer(
        task_id="golden.rollback_and_failure_learning",
        title="Failure examples make regressions visible and recoverable",
        beneficiaries=[
            "on-call maintainers who need quick diagnosis when a change regresses",
            "benchmark authors separating robust behaviour from lucky passes",
            "agents learning from negative examples instead of hiding them",
        ],
        counter_metrics=[
            "count missing negative examples for every newly promoted golden task",
            "flag tasks that define success but no realistic failure signature",
            "penalise fixes that remove failing cases instead of explaining them",
        ],
        failure_examples=[
            FailureExample(
                name="green-by-deletion",
                symptom="a troublesome scenario is removed from the suite and the aggregate score improves",
                why_it_is_bad="the benchmark becomes easier while the real-world failure remains unhandled",
            ),
            FailureExample(
                name="unactionable red",
                symptom="the task fails with no named beneficiary, counter-signal, or reproduction clue",
                why_it_is_bad="failure cannot guide repair, so the benchmark detects pain without enabling progress",
            ),
        ],
    ),
}


def get_hot_golden_anticheat_layers() -> List[Dict[str, object]]:
    """Return all hot golden anti-cheat layers as serialisable dictionaries."""

    return [layer.as_dict() for layer in HOT_GOLDEN_ANTI_CHEAT_LAYERS.values()]


def layer_for(task_id: str) -> Optional[Dict[str, object]]:
    """Return the anti-cheat layer for *task_id*, if this registry covers it."""

    layer = HOT_GOLDEN_ANTI_CHEAT_LAYERS.get(task_id)
    if layer is None:
        return None
    return layer.as_dict()


def annotate_tasks(tasks: Iterable[Mapping[str, object]]) -> List[Dict[str, object]]:
    """Attach anti-cheat metadata to matching task dictionaries.

    Unknown tasks are copied unchanged.  Matching tasks receive an
    ``anti_cheat_layer`` key without mutating the input objects.
    """

    annotated: List[Dict[str, object]] = []
    for task in tasks:
        copied: MutableMapping[str, object] = dict(task)
        task_id = str(copied.get("task_id") or copied.get("id") or "")
        layer = layer_for(task_id)
        if layer is not None:
            copied["anti_cheat_layer"] = layer
        annotated.append(dict(copied))
    return annotated
