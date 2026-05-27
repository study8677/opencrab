"""Blind replay utilities for patchcourse brain-only patch practice.

The goal is to turn historical small repairs into repeatable blind drills:
only the buggy input is shown to a patch-producing brain, while the known
answer is kept aside for scoring.

This module is intentionally dependency-light and side-effect free so it can
be used by tests, notebooks, or future CLI glue without pulling in the rest of
the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import unified_diff
from typing import Callable, Iterable, List, Mapping, Optional, Sequence, Tuple


PatchBrain = Callable[["BlindPatchCase"], str]


@dataclass(frozen=True)
class BlindPatchCase:
    """A historical repair with the answer hidden from the patch brain."""

    case_id: str
    path: str
    before: str
    hint: str = ""

    def prompt(self) -> str:
        """Return a compact text prompt suitable for a brain-only patcher."""

        parts = [
            f"case_id: {self.case_id}",
            f"path: {self.path}",
        ]
        if self.hint:
            parts.append(f"hint: {self.hint}")
        parts.extend(["before:", self.before])
        return "\n".join(parts)


@dataclass(frozen=True)
class HistoricalPatch:
    """A replayable historical small repair."""

    case_id: str
    path: str
    before: str
    after: str
    hint: str = ""

    def blind_case(self) -> BlindPatchCase:
        return BlindPatchCase(
            case_id=self.case_id,
            path=self.path,
            before=self.before,
            hint=self.hint,
        )

    def expected_diff(self, context: int = 3) -> str:
        return text_diff(self.before, self.after, self.path, context=context)


@dataclass(frozen=True)
class BlindReplayResult:
    """Score for one blind replay attempt."""

    case_id: str
    path: str
    hit: bool
    misfire: bool
    expected_after: str
    produced_after: str
    expected_diff: str
    produced_diff: str
    error: str = ""

    @property
    def clean_miss(self) -> bool:
        """A miss that changed nothing and therefore did not misfire."""

        return not self.hit and not self.misfire and not self.error


@dataclass(frozen=True)
class BlindReplayReport:
    """Aggregate metrics for a blind replay batch."""

    total: int
    hits: int
    misses: int
    misfires: int
    errors: int
    results: Tuple[BlindReplayResult, ...]

    @property
    def hit_rate(self) -> float:
        return _ratio(self.hits, self.total)

    @property
    def misfire_rate(self) -> float:
        return _ratio(self.misfires, self.total)

    @property
    def error_rate(self) -> float:
        return _ratio(self.errors, self.total)

    def summary(self) -> Mapping[str, float]:
        return {
            "total": float(self.total),
            "hits": self.hit_rate,
            "misfires": self.misfire_rate,
            "errors": self.error_rate,
        }


def text_diff(before: str, after: str, path: str = "case.py", context: int = 3) -> str:
    """Return a stable unified diff for two text snapshots."""

    before_lines = before.splitlines(keepends=True)
    after_lines = after.splitlines(keepends=True)
    return "".join(
        unified_diff(
            before_lines,
            after_lines,
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=context,
            lineterm="",
        )
    )


def normalize_text(text: str) -> str:
    """Normalize only trailing whitespace and final newline noise for scoring."""

    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).rstrip("\n")


def score_attempt(case: HistoricalPatch, produced_after: str) -> BlindReplayResult:
    """Score one produced repair against the hidden historical answer."""

    expected_norm = normalize_text(case.after)
    produced_norm = normalize_text(produced_after)
    before_norm = normalize_text(case.before)

    hit = produced_norm == expected_norm
    changed = produced_norm != before_norm
    misfire = changed and not hit

    return BlindReplayResult(
        case_id=case.case_id,
        path=case.path,
        hit=hit,
        misfire=misfire,
        expected_after=case.after,
        produced_after=produced_after,
        expected_diff=case.expected_diff(),
        produced_diff=text_diff(case.before, produced_after, case.path),
    )


def replay_case(case: HistoricalPatch, brain: PatchBrain) -> BlindReplayResult:
    """Run a brain-only patcher on one hidden-answer case."""

    blind = case.blind_case()
    try:
        produced_after = brain(blind)
    except Exception as exc:  # pragma: no cover - caller supplied brain
        return BlindReplayResult(
            case_id=case.case_id,
            path=case.path,
            hit=False,
            misfire=False,
            expected_after=case.after,
            produced_after=case.before,
            expected_diff=case.expected_diff(),
            produced_diff="",
            error=f"{type(exc).__name__}: {exc}",
        )
    return score_attempt(case, produced_after)


def replay_cases(
    cases: Iterable[HistoricalPatch],
    brain: PatchBrain,
    limit: Optional[int] = None,
) -> BlindReplayReport:
    """Replay a batch of cases and compute hit/misfire/error rates."""

    results: List[BlindReplayResult] = []
    for index, case in enumerate(cases):
        if limit is not None and index >= limit:
            break
        results.append(replay_case(case, brain))

    total = len(results)
    hits = sum(1 for result in results if result.hit)
    errors = sum(1 for result in results if result.error)
    misfires = sum(1 for result in results if result.misfire)
    misses = total - hits

    return BlindReplayReport(
        total=total,
        hits=hits,
        misses=misses,
        misfires=misfires,
        errors=errors,
        results=tuple(results),
    )


def cases_from_dicts(rows: Iterable[Mapping[str, str]]) -> Tuple[HistoricalPatch, ...]:
    """Build replay cases from dictionaries with before/after snapshots.

    Required keys: ``case_id``, ``path``, ``before``, ``after``.
    Optional key: ``hint``.
    """

    cases: List[HistoricalPatch] = []
    for row in rows:
        missing = [key for key in ("case_id", "path", "before", "after") if key not in row]
        if missing:
            raise ValueError(f"historical patch row missing keys: {', '.join(missing)}")
        cases.append(
            HistoricalPatch(
                case_id=row["case_id"],
                path=row["path"],
                before=row["before"],
                after=row["after"],
                hint=row.get("hint", ""),
            )
        )
    return tuple(cases)


def exact_answer_brain(answers: Mapping[str, str]) -> PatchBrain:
    """Return a deterministic brain useful for calibration and tests."""

    def brain(case: BlindPatchCase) -> str:
        return answers.get(case.case_id, case.before)

    return brain


def top_misfires(
    report: BlindReplayReport,
    max_items: int = 5,
) -> Tuple[BlindReplayResult, ...]:
    """Return the first misfiring attempts for quick inspection."""

    if max_items <= 0:
        return ()
    return tuple(result for result in report.results if result.misfire)[:max_items]


__all__ = [
    "BlindPatchCase",
    "BlindReplayReport",
    "BlindReplayResult",
    "HistoricalPatch",
    "PatchBrain",
    "cases_from_dicts",
    "exact_answer_brain",
    "normalize_text",
    "replay_case",
    "replay_cases",
    "score_attempt",
    "text_diff",
    "top_misfires",
]


def _ratio(part: int, total: int) -> float:
    if total <= 0:
        return 0.0
    return part / total
