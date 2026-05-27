"""Pre-flight failure recall for patchfitroom.

This module is intentionally defensive: handsdojo and moveset have evolved
independently over time, so the recall layer accepts many common shapes
(functions, lists, dicts, objects) and degrades to deterministic built-in
bad-patch regressions when no historical failure source is available.
"""

from __future__ import annotations

import difflib
import importlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence


_BAD_PATCH_CASES = (
    {
        "id": "badpatch.syntax.poison",
        "title": "unbalanced function definition should be recalled before fit",
        "patch": "def definitely_broken(:\n    pass\n",
        "reason": "syntax",
        "tags": ("syntax", "bad-patch", "preflight"),
    },
    {
        "id": "badpatch.shell.rm_rf",
        "title": "destructive shell command should be recalled before fit",
        "patch": "import os\nos.system('rm -rf /')\n",
        "reason": "dangerous-shell",
        "tags": ("shell", "destructive", "bad-patch", "preflight"),
    },
    {
        "id": "badpatch.conflict.marker",
        "title": "merge conflict markers should be recalled before fit",
        "patch": "<<<<<<< ours\nprint('a')\n=======\nprint('b')\n>>>>>>> theirs\n",
        "reason": "conflict-marker",
        "tags": ("conflict", "bad-patch", "preflight"),
    },
)


@dataclass(frozen=True)
class FailureRecall:
    """A recalled failure that resembles an incoming patch."""

    source: str
    identifier: str
    score: float
    title: str
    reason: str
    patch: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source,
            "id": self.identifier,
            "score": round(self.score, 6),
            "title": self.title,
            "reason": self.reason,
            "patch": self.patch,
        }


def _tokens(text: str) -> List[str]:
    return re.findall(r"[A-Za-z_][A-Za-z0-9_]*|<<<<<<<|=======|>>>>>>>|rm\s+-rf|os\.system|subprocess", text)


def _similarity(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return difflib.SequenceMatcher(None, left, right).ratio()
    overlap = len(left_tokens & right_tokens) / float(len(left_tokens | right_tokens))
    sequence = difflib.SequenceMatcher(None, left, right).ratio()
    return (overlap * 0.7) + (sequence * 0.3)


def _iter_named_sources(module_name: str) -> Iterable[Any]:
    try:
        module = importlib.import_module(module_name)
    except Exception:
        return ()

    names = (
        "similar_failures",
        "recent_failures",
        "failure_cases",
        "failed_cases",
        "bad_patches",
        "BAD_PATCHES",
        "FAILURES",
        "FAILED_MOVES",
        "MOVES",
    )
    found: List[Any] = []
    for name in names:
        if not hasattr(module, name):
            continue
        value = getattr(module, name)
        try:
            value = value() if callable(value) and name.islower() else value
        except TypeError:
            continue
        except Exception:
            continue
        found.append(value)
    return found


def _flatten(value: Any) -> Iterable[Any]:
    if value is None:
        return
    if isinstance(value, Mapping):
        if any(key in value for key in ("patch", "diff", "title", "reason", "id", "name")):
            yield value
            return
        for nested in value.values():
            yield from _flatten(nested)
        return
    if isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten(item)
        return
    yield value


def _field(record: Any, *names: str, default: str = "") -> str:
    for name in names:
        if isinstance(record, Mapping) and name in record:
            return str(record.get(name) or default)
        if hasattr(record, name):
            return str(getattr(record, name) or default)
    return default


def _history_records() -> Iterable[tuple[str, Any]]:
    for source in ("handsdojo", "moveset"):
        for collection in _iter_named_sources(source):
            for record in _flatten(collection):
                yield source, record


def recall_similar_failures(patch_text: str, limit: int = 3, min_score: float = 0.08) -> List[Dict[str, Any]]:
    """Return up to *limit* historical or built-in failures similar to patch_text."""

    candidates: List[FailureRecall] = []
    for source, record in _history_records():
        patch = _field(record, "patch", "diff", "content", "text", "body")
        title = _field(record, "title", "name", "summary", default="historical failure")
        reason = _field(record, "reason", "error", "failure", "kind", default="similar failure")
        identifier = _field(record, "id", "identifier", "name", default=title)
        haystack = "\n".join(part for part in (patch, title, reason) if part)
        score = _similarity(patch_text, haystack)
        if score >= min_score:
            candidates.append(FailureRecall(source, identifier, score, title, reason, patch))

    for case in _BAD_PATCH_CASES:
        haystack = "\n".join((case["patch"], case["title"], case["reason"], " ".join(case["tags"])))
        score = _similarity(patch_text, haystack)
        if score >= min_score:
            candidates.append(
                FailureRecall(
                    "builtin-badpatch-regression",
                    case["id"],
                    score,
                    case["title"],
                    case["reason"],
                    case["patch"],
                )
            )

    candidates.sort(key=lambda item: item.score, reverse=True)
    return [item.as_dict() for item in candidates[: max(0, limit)]]


def preflight_patch(patch_text: str, limit: int = 3) -> Dict[str, Any]:
    """Patchfitroom-facing preflight result.

    The patch is not rejected here; callers can decide whether recalled failures
    are advisory or blocking.
    """

    recalls = recall_similar_failures(patch_text, limit=limit)
    return {
        "ok": True,
        "checked": True,
        "recall_count": len(recalls),
        "recalls": recalls,
    }


def run_bad_patch_regression() -> Dict[str, Any]:
    """Run the three built-in bad-patch recall regressions."""

    results = []
    for case in _BAD_PATCH_CASES:
        recalls = recall_similar_failures(case["patch"], limit=3, min_score=0.01)
        matched = any(item.get("id") == case["id"] for item in recalls)
        results.append(
            {
                "id": case["id"],
                "matched": matched,
                "top": recalls[0]["id"] if recalls else None,
                "recall_count": len(recalls),
            }
        )
    return {
        "ok": all(item["matched"] for item in results),
        "case_count": len(results),
        "results": results,
    }


if __name__ == "__main__":
    outcome = run_bad_patch_regression()
    if not outcome["ok"]:
        raise SystemExit(1)
    print(outcome)
