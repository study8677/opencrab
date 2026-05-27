"""Brain-only external-helper circuit-breaker drill for hands.

This module is intentionally self-contained: it does not call shells, network
APIs, subprocesses, or external model helpers.  The default drill disables the
``claude`` helper and proves a tiny documentation repair can be planned,
patched, reviewed, and summarized by local Python code only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence


DEFAULT_BLOCKED_HELPERS = ("claude",)
DEFAULT_DOC = "Hands drill: brain-only doc fix.\n\nStatus: exteranl aid disabled.\n"
DEFAULT_TYPO = "exteranl"
DEFAULT_FIX = "external"


@dataclass(frozen=True)
class BrainOnlyDocPatch:
    """A minimal documentation patch produced without external helpers."""

    before: str
    after: str
    old: str
    new: str

    @property
    def changed(self) -> bool:
        return self.before != self.after

    @property
    def replacements(self) -> int:
        return self.before.count(self.old)


@dataclass(frozen=True)
class HandsBreakerDrillResult:
    """Result of the external-helper breaker drill."""

    blocked_helpers: tuple[str, ...]
    requested_helpers: tuple[str, ...]
    patch: BrainOnlyDocPatch
    passed: bool
    notes: tuple[str, ...]


def _normalize_names(names: Iterable[str]) -> tuple[str, ...]:
    return tuple(str(name).strip().lower() for name in names if str(name).strip())


def assert_brain_only(
    requested_helpers: Iterable[str] = (),
    blocked_helpers: Iterable[str] = DEFAULT_BLOCKED_HELPERS,
) -> tuple[str, ...]:
    """Raise if the drill attempts to use a blocked external helper.

    The function returns the normalized blocked-helper list so callers can
    record the active breaker state in their evidence.
    """

    requested = set(_normalize_names(requested_helpers))
    blocked = _normalize_names(blocked_helpers)
    forbidden = sorted(requested.intersection(blocked))
    if forbidden:
        raise RuntimeError(
            "external helper circuit breaker tripped: "
            + ", ".join(forbidden)
        )
    return blocked


def make_brain_only_doc_patch(
    doc: str = DEFAULT_DOC,
    old: str = DEFAULT_TYPO,
    new: str = DEFAULT_FIX,
) -> BrainOnlyDocPatch:
    """Create a tiny deterministic documentation fix using local string logic."""

    if not old:
        raise ValueError("old text must be non-empty")
    after = doc.replace(old, new)
    return BrainOnlyDocPatch(before=doc, after=after, old=old, new=new)


def review_doc_patch(patch: BrainOnlyDocPatch) -> tuple[bool, tuple[str, ...]]:
    """Review the local documentation patch with simple deterministic checks."""

    notes: list[str] = []
    if not patch.changed:
        notes.append("no documentation change was made")
    if patch.old in patch.after:
        notes.append("old typo still present after patch")
    if patch.new not in patch.after:
        notes.append("replacement text missing after patch")
    if patch.replacements != 1:
        notes.append(f"expected exactly one replacement, saw {patch.replacements}")
    if "\n" not in patch.after:
        notes.append("patched documentation should remain line-oriented")
    if not notes:
        notes.append("brain-only documentation patch reviewed cleanly")
    return (len(notes) == 1 and notes[0].endswith("cleanly"), tuple(notes))


def run_drill(
    doc: str = DEFAULT_DOC,
    requested_helpers: Sequence[str] = (),
    blocked_helpers: Sequence[str] = DEFAULT_BLOCKED_HELPERS,
) -> HandsBreakerDrillResult:
    """Run the no-external-helper drill end to end."""

    blocked = assert_brain_only(requested_helpers, blocked_helpers)
    patch = make_brain_only_doc_patch(doc)
    passed, review_notes = review_doc_patch(patch)
    notes = (
        "claude disabled by circuit breaker"
        if "claude" in blocked
        else "external helper breaker active"
    ,) + review_notes
    return HandsBreakerDrillResult(
        blocked_helpers=blocked,
        requested_helpers=_normalize_names(requested_helpers),
        patch=patch,
        passed=passed,
        notes=notes,
    )


def format_result(result: HandsBreakerDrillResult) -> str:
    """Render compact human-readable drill evidence."""

    status = "PASS" if result.passed else "FAIL"
    helpers = ", ".join(result.blocked_helpers) or "(none)"
    notes = "; ".join(result.notes)
    return (
        f"{status} hands external-breaker drill: blocked=[{helpers}], "
        f"changed={result.patch.changed}, notes={notes}"
    )


def main() -> int:
    result = run_drill()
    print(format_result(result))
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
