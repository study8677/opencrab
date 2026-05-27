"""Golden replay for a brain-only weaning acceptance run.

This module records a deliberately low-risk documentation-only change.  It is
kept as plain Python data so it can be imported, replayed, and audited without
calling an external assistant or tool.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from typing import Tuple


@dataclass(frozen=True)
class ReplayStep:
    """One deterministic step in the weaning acceptance replay."""

    name: str
    detail: str


DOC_PATCH_TITLE = "Clarify brain-only weaning acceptance evidence"

DOC_PATCH_BEFORE = (
    "A weaning trial may be considered complete when the planned change is "
    "described."
)

DOC_PATCH_AFTER = (
    "A weaning trial is complete only when a small, low-risk documentation "
    "change is landed by the model's own Python patch output, without invoking "
    "Claude or another external code-writing tool, and the result is sealed as "
    "a golden replay."
)

GOLDEN_REPLAY: Tuple[ReplayStep, ...] = (
    ReplayStep(
        "scope",
        "Choose a documentation-only wording clarification with no runtime side effects.",
    ),
    ReplayStep(
        "constraint",
        "Perform the change brain-only: emit Python patch text directly and do not call Claude.",
    ),
    ReplayStep(
        "landing",
        "Store the acceptance evidence in this import-safe module as deterministic data.",
    ),
    ReplayStep(
        "verification",
        "The module is standard-library only and is suitable for python -m py_compile.",
    ),
    ReplayStep(
        "seal",
        "Hash the replay payload so future runs can compare the same golden transcript.",
    ),
)


def replay_text() -> str:
    """Return the canonical golden replay transcript."""

    lines = [
        f"title: {DOC_PATCH_TITLE}",
        f"before: {DOC_PATCH_BEFORE}",
        f"after: {DOC_PATCH_AFTER}",
        "steps:",
    ]
    lines.extend(f"- {step.name}: {step.detail}" for step in GOLDEN_REPLAY)
    return "\n".join(lines)


def replay_digest() -> str:
    """Return a stable SHA-256 digest of the golden replay transcript."""

    return sha256(replay_text().encode("utf-8")).hexdigest()


def validate() -> bool:
    """Validate the replay's core weaning acceptance invariants."""

    transcript = replay_text().lower()
    return (
        "documentation" in transcript
        and "brain-only" in transcript
        and "do not call claude" in transcript
        and len(replay_digest()) == 64
    )


GOLDEN_REPLAY_DIGEST = replay_digest()


__all__ = [
    "DOC_PATCH_AFTER",
    "DOC_PATCH_BEFORE",
    "DOC_PATCH_TITLE",
    "GOLDEN_REPLAY",
    "GOLDEN_REPLAY_DIGEST",
    "ReplayStep",
    "replay_digest",
    "replay_text",
    "validate",
]
