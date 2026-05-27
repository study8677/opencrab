"""Default brain-only routing policy for the weaning gate.

The helpers here are intentionally dependency-free so hands.py and
weaning_gate.py can use them without pulling in external execution paths.
Low-risk documentation and small pure-function fixes should try the
brain-only route first; callers can record the returned downgrade reason
when that route fails and they need to fall back to external fitting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


_DOC_EXTENSIONS = {
    ".md",
    ".rst",
    ".txt",
    ".adoc",
}
_CODE_EXTENSIONS = {
    ".py",
}


@dataclass(frozen=True)
class BrainOnlyRouteDecision:
    """A small, serialisable routing decision for weaning-aware hands."""

    brain_only: bool
    reason: str
    downgrade_reason: str = ""

    def as_dict(self) -> dict[str, object]:
        return {
            "brain_only": self.brain_only,
            "reason": self.reason,
            "downgrade_reason": self.downgrade_reason,
        }


def _normalise_paths(paths: Iterable[str] | None) -> tuple[str, ...]:
    if not paths:
        return ()
    return tuple(str(path).strip() for path in paths if str(path).strip())


def _extension(path: str) -> str:
    dot = path.rfind(".")
    if dot < 0:
        return ""
    return path[dot:].lower()


def _looks_like_doc_only(paths: Sequence[str]) -> bool:
    return bool(paths) and all(_extension(path) in _DOC_EXTENSIONS for path in paths)


def _looks_like_small_python_patch(paths: Sequence[str], changed_lines: int) -> bool:
    return (
        bool(paths)
        and changed_lines <= 80
        and all(_extension(path) in _CODE_EXTENSIONS for path in paths)
    )


def _mentions_pure_function(intent: str) -> bool:
    lowered = intent.lower()
    markers = (
        "pure function",
        "pure-function",
        "purefn",
        "纯函数",
        "无副作用",
        "small pure",
    )
    return any(marker in lowered for marker in markers)


def _has_high_risk_marker(intent: str, paths: Sequence[str]) -> bool:
    lowered = intent.lower()
    high_risk_words = (
        "schema",
        "migration",
        "secret",
        "credential",
        "network",
        "subprocess",
        "socket",
        "delete",
        "remove data",
        "database",
        "权限",
        "密钥",
        "凭证",
        "迁移",
        "删除数据",
    )
    if any(word in lowered for word in high_risk_words):
        return True
    risky_path_parts = (
        "secrets",
        "supplychain",
        "license",
        "permission",
        "privacy",
        "migration",
    )
    return any(any(part in path.lower() for part in risky_path_parts) for path in paths)


def decide_brain_only_default(
    *,
    changed_paths: Iterable[str] | None = None,
    changed_lines: int = 0,
    intent: str = "",
    previous_brain_only_failure: str = "",
) -> BrainOnlyRouteDecision:
    """Choose the default weaning route for a proposed small change.

    The policy is conservative:
    * docs-only changes go brain-only first;
    * small Python patches explicitly described as pure-function fixes go
      brain-only first;
    * known high-risk markers keep the external fit-room available;
    * if a prior brain-only attempt failed, return a downgrade reason so the
      caller can log why it is falling back.
    """

    paths = _normalise_paths(changed_paths)
    safe_line_count = max(0, int(changed_lines or 0))
    intent_text = str(intent or "")
    prior_failure = str(previous_brain_only_failure or "").strip()

    if prior_failure:
        return BrainOnlyRouteDecision(
            brain_only=False,
            reason="brain_only_failed",
            downgrade_reason=prior_failure,
        )

    if _has_high_risk_marker(intent_text, paths):
        return BrainOnlyRouteDecision(
            brain_only=False,
            reason="high_risk_marker_keeps_external_fitroom_available",
        )

    if _looks_like_doc_only(paths):
        return BrainOnlyRouteDecision(
            brain_only=True,
            reason="low_risk_docs_default_to_brain_only",
        )

    if _looks_like_small_python_patch(paths, safe_line_count) and _mentions_pure_function(intent_text):
        return BrainOnlyRouteDecision(
            brain_only=True,
            reason="small_pure_function_fix_default_to_brain_only",
        )

    return BrainOnlyRouteDecision(
        brain_only=False,
        reason="not_low_risk_brain_only_candidate",
    )


def record_brain_only_downgrade(
    decision: BrainOnlyRouteDecision,
    failure_reason: str,
) -> Mapping[str, object]:
    """Return a compact downgrade event after a brain-only route fails."""

    reason = str(failure_reason or "").strip() or "brain_only_attempt_failed"
    return {
        "brain_only": False,
        "reason": "downgraded_after_brain_only_failure",
        "downgrade_reason": reason,
        "previous_decision": decision.as_dict(),
    }
