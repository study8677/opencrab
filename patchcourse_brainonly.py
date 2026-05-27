"""Brain-only patchcourse lessons distilled from failed handsdojo samples.

This module is intentionally pure-Python and side-effect free: it performs no
file IO, shell calls, network access, or imports from the rest of the project.
It turns small failure records into deterministic micro-fix lessons that can be
rerun by tests, mentors, or future training loops.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha1
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class FailureSample:
    """A compact record of a failed patch attempt."""

    name: str
    symptom: str
    bad_patch: str
    lesson: str
    expected_fix: str


@dataclass(frozen=True)
class BrainOnlyLesson:
    """A rerunnable micro-fix exercise that needs only reasoning over text."""

    lesson_id: str
    title: str
    prompt: str
    bad_patch: str
    expected_fix: str
    checks: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        """Return a JSON-serialisable representation for simple runners."""

        return {
            "lesson_id": self.lesson_id,
            "title": self.title,
            "prompt": self.prompt,
            "bad_patch": self.bad_patch,
            "expected_fix": self.expected_fix,
            "checks": list(self.checks),
        }


THREE_FAILED_SAMPLES: tuple[FailureSample, ...] = (
    FailureSample(
        name="unique-old-fragment",
        symptom="An EDIT block was skipped because ---OLD--- matched more than once.",
        bad_patch=(
            "<<<EDIT path=example.py>>>\n"
            "---OLD---\n"
            "    return None\n"
            "---NEW---\n"
            "    return value\n"
            "<<<END>>>"
        ),
        lesson=(
            "Make the replacement anchor unique by including nearby function or "
            "branch context instead of editing a repeated one-line fragment."
        ),
        expected_fix=(
            "Use a larger OLD span containing the surrounding def/if context so "
            "the fragment is unique before replacing it."
        ),
    ),
    FailureSample(
        name="brain-only-no-tools",
        symptom="The attempted fix depended on running external commands.",
        bad_patch=(
            "I will inspect the repo with grep, run tests, then decide what to patch."
        ),
        lesson=(
            "For brain-only repair, ship deterministic text transforms or fixtures "
            "that can be reasoned about without shell, filesystem, or network access."
        ),
        expected_fix=(
            "Create a pure helper with embedded samples and deterministic checks; "
            "avoid subprocess, open(), pathlib IO, sockets, and test-run assumptions."
        ),
    ),
    FailureSample(
        name="small-safe-course",
        symptom="The patch rewrote a large core file to add a tiny training feature.",
        bad_patch=(
            "<<<WRITE path=crab.py>>>\n"
            "# complete large-file rewrite for a small lesson feature\n"
            "<<<END>>>"
        ),
        lesson=(
            "Prefer a narrow new module or a tiny EDIT over rewriting large hot files."
        ),
        expected_fix=(
            "Add the course as a small standalone module with a stable public function "
            "and no import-time side effects."
        ),
    ),
)


_FORBIDDEN_BRAIN_ONLY_TOKENS: tuple[str, ...] = (
    "subprocess",
    "os.system",
    "Path(",
    "open(",
    "socket",
    "requests",
    "urllib",
)


def _stable_lesson_id(sample: FailureSample) -> str:
    seed = "\n".join((sample.name, sample.symptom, sample.lesson, sample.expected_fix))
    return "brain-only-" + sha1(seed.encode("utf-8")).hexdigest()[:12]


def lesson_from_failure(sample: FailureSample) -> BrainOnlyLesson:
    """Convert one failed sample into a deterministic micro-fix lesson."""

    title = sample.name.replace("-", " ").title()
    prompt = (
        f"Failure symptom: {sample.symptom}\n"
        f"Why it failed: {sample.lesson}\n"
        "Task: propose the smallest brain-only patch that fixes this failure mode."
    )
    checks = (
        "patch is deterministic",
        "patch is small and reviewable",
        "patch does not require external tools",
        "patch states the repair rule explicitly",
    )
    return BrainOnlyLesson(
        lesson_id=_stable_lesson_id(sample),
        title=title,
        prompt=prompt,
        bad_patch=sample.bad_patch,
        expected_fix=sample.expected_fix,
        checks=checks,
    )


def build_brain_only_course(
    failures: Iterable[FailureSample] = THREE_FAILED_SAMPLES,
) -> tuple[BrainOnlyLesson, ...]:
    """Build a rerunnable patchcourse from failure samples."""

    return tuple(lesson_from_failure(sample) for sample in failures)


def default_course_dicts() -> list[dict[str, object]]:
    """Return the built-in three-lesson course as plain dictionaries."""

    return [lesson.as_dict() for lesson in build_brain_only_course()]


def score_brain_only_answer(answer: str, lesson: BrainOnlyLesson) -> dict[str, object]:
    """Score a proposed answer with simple deterministic brain-only checks.

    The scorer is deliberately conservative: it does not execute the answer.
    It only looks for signs that the response follows the lesson constraints.
    """

    lowered = answer.lower()
    forbidden_hits = [
        token for token in _FORBIDDEN_BRAIN_ONLY_TOKENS if token.lower() in lowered
    ]
    has_small_patch_shape = (
        "<<<write " in lowered
        or "<<<edit " in lowered
        or "small" in lowered
        or "standalone" in lowered
    )
    mentions_rule = any(word in lowered for word in ("unique", "pure", "deterministic", "small"))
    passes = not forbidden_hits and has_small_patch_shape and mentions_rule
    return {
        "lesson_id": lesson.lesson_id,
        "passes": passes,
        "forbidden_hits": forbidden_hits,
        "has_small_patch_shape": has_small_patch_shape,
        "mentions_repair_rule": mentions_rule,
    }


def score_course_answers(
    answers: Mapping[str, str],
    lessons: Sequence[BrainOnlyLesson] | None = None,
) -> list[dict[str, object]]:
    """Score answers keyed by lesson_id for a whole brain-only course."""

    course = tuple(lessons) if lessons is not None else build_brain_only_course()
    return [
        score_brain_only_answer(answers.get(lesson.lesson_id, ""), lesson)
        for lesson in course
    ]


__all__ = [
    "BrainOnlyLesson",
    "FailureSample",
    "THREE_FAILED_SAMPLES",
    "build_brain_only_course",
    "default_course_dicts",
    "lesson_from_failure",
    "score_brain_only_answer",
    "score_course_answers",
]
