"""Brain-only patch rejection attribution for patchfitroom.

This module is intentionally small and dependency-free so patchfitroom can call it
from failure paths without risking a second failure.  It turns raw exceptions,
logs, or replay results into a stable attribution label plus the smallest useful
rework hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional


SYNTAX = "syntax"
IMPORT = "import"
REPLAY_GATE = "replay_gate"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class BrainOnlyRejectAttribution:
    """Stable attribution emitted when a brain-only patch is rejected."""

    bucket: str
    hint: str
    evidence: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "bucket": self.bucket,
            "hint": self.hint,
            "evidence": self.evidence,
        }


def attribute_brainonly_rejection(
    failure: Any = None,
    *,
    stderr: str = "",
    stdout: str = "",
    replay: Any = None,
) -> BrainOnlyRejectAttribution:
    """Classify why a brain-only patch was rejected.

    Priority is deliberately strict:
    1. Python syntax/compile failures.
    2. Import/load failures.
    3. Replay gate failures.
    4. Unknown fallback.

    Args:
        failure: Exception, string, mapping, or arbitrary failure object.
        stderr: Captured stderr from compile/import/replay steps.
        stdout: Captured stdout from compile/import/replay steps.
        replay: Optional replay result object or mapping.

    Returns:
        BrainOnlyRejectAttribution with a stable bucket and minimal rework hint.
    """

    text = _failure_text(failure, stderr=stderr, stdout=stdout, replay=replay)

    if _is_syntax_failure(failure, text):
        return BrainOnlyRejectAttribution(
            SYNTAX,
            "Fix the smallest invalid Python span first; run py_compile before retrying.",
            _trim_evidence(text),
        )

    if _is_import_failure(failure, text):
        return BrainOnlyRejectAttribution(
            IMPORT,
            "Fix the missing or crashing import path; verify the touched module imports cleanly.",
            _trim_evidence(text),
        )

    if _is_replay_gate_failure(replay, text):
        return BrainOnlyRejectAttribution(
            REPLAY_GATE,
            "Keep the patch shape but adjust behavior to satisfy the failing replay gate.",
            _trim_evidence(text),
        )

    return BrainOnlyRejectAttribution(
        UNKNOWN,
        "Re-run with compile, import, and replay output captured so the rejection can be attributed.",
        _trim_evidence(text),
    )


def minimal_rework_hint(bucket: str) -> str:
    """Return the canonical short rework hint for an attribution bucket."""

    if bucket == SYNTAX:
        return "Fix the smallest invalid Python span first; run py_compile before retrying."
    if bucket == IMPORT:
        return "Fix the missing or crashing import path; verify the touched module imports cleanly."
    if bucket == REPLAY_GATE:
        return "Keep the patch shape but adjust behavior to satisfy the failing replay gate."
    return "Re-run with compile, import, and replay output captured so the rejection can be attributed."


def _failure_text(
    failure: Any,
    *,
    stderr: str = "",
    stdout: str = "",
    replay: Any = None,
) -> str:
    parts: list[str] = []

    for item in (failure, replay):
        if item is None:
            continue
        if isinstance(item, BaseException):
            parts.append(type(item).__name__)
            parts.append(str(item))
        elif isinstance(item, Mapping):
            for key in sorted(item):
                try:
                    parts.append(f"{key}={item[key]}")
                except Exception:
                    parts.append(str(key))
        else:
            parts.append(str(item))

    if stderr:
        parts.append(stderr)
    if stdout:
        parts.append(stdout)

    return "\n".join(part for part in parts if part)


def _is_syntax_failure(failure: Any, text: str) -> bool:
    if isinstance(failure, SyntaxError):
        return True

    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "syntaxerror",
            "indentationerror",
            "taberror",
            "invalid syntax",
            "unexpected indent",
            "expected an indented block",
            "was never closed",
            "eof while scanning",
            "unterminated string literal",
        )
    )


def _is_import_failure(failure: Any, text: str) -> bool:
    if isinstance(failure, (ImportError, ModuleNotFoundError)):
        return True

    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "importerror",
            "modulenotfounderror",
            "no module named",
            "cannot import name",
            "attempted relative import",
            "failed to import",
            "import failed",
        )
    )


def _is_replay_gate_failure(replay: Any, text: str) -> bool:
    if isinstance(replay, Mapping):
        status = str(replay.get("status", "")).lower()
        gate = str(replay.get("gate", "")).lower()
        reason = str(replay.get("reason", "")).lower()
        passed = replay.get("passed")
        ok = replay.get("ok")

        if passed is False or ok is False:
            if "replay" in gate or "gate" in gate or "replay" in reason:
                return True
        if status in {"failed", "fail", "rejected", "blocked"} and (
            "replay" in gate or "replay" in reason
        ):
            return True

    lowered = text.lower()
    return any(
        marker in lowered
        for marker in (
            "replay gate",
            "replay_gate",
            "golden replay",
            "blind replay",
            "replay failed",
            "replay mismatch",
            "replay rejected",
            "gate failed",
            "gate rejected",
        )
    )


def _trim_evidence(text: str, limit: int = 240) -> str:
    compact = " ".join(text.split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1].rstrip() + "…"


__all__ = [
    "IMPORT",
    "REPLAY_GATE",
    "SYNTAX",
    "UNKNOWN",
    "BrainOnlyRejectAttribution",
    "attribute_brainonly_rejection",
    "minimal_rework_hint",
]
