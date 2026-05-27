"""Semantic de-duplication for feedback signals.

The module accepts feedback from issues, userlab notes, or outside
observations, builds a stable semantic fingerprint, and merges repeated
signals without losing their heat or first cause.

The public entry point is :func:`deduplicate_feedback`.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple


_WORD_RE = re.compile(r"[a-z0-9\u4e00-\u9fff]+", re.IGNORECASE)

_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
    "我",
    "们",
    "的",
    "了",
    "是",
    "在",
    "和",
    "与",
    "就",
    "都",
    "而",
    "及",
    "或",
    "也",
    "很",
}

_SYNONYMS = {
    "bug": "defect",
    "bugs": "defect",
    "crash": "failure",
    "crashes": "failure",
    "failed": "failure",
    "fails": "failure",
    "fail": "failure",
    "error": "failure",
    "errors": "failure",
    "exception": "failure",
    "exceptions": "failure",
    "slow": "latency",
    "slower": "latency",
    "timeout": "latency",
    "timeouts": "latency",
    "lag": "latency",
    "confusing": "unclear",
    "confused": "unclear",
    "duplicate": "repeat",
    "duplicated": "repeat",
    "duplicates": "repeat",
    "问题": "defect",
    "错误": "defect",
    "异常": "failure",
    "失败": "failure",
    "崩溃": "failure",
    "卡顿": "latency",
    "超时": "latency",
    "慢": "latency",
    "重复": "repeat",
    "噪声": "noise",
}


def _as_mapping(item: Any) -> Mapping[str, Any]:
    if isinstance(item, Mapping):
        return item
    data: Dict[str, Any] = {}
    for name in ("title", "summary", "body", "text", "content", "source", "cause", "heat"):
        if hasattr(item, name):
            data[name] = getattr(item, name)
    if data:
        return data
    return {"text": str(item)}


def normalize_text(text: Any) -> str:
    """Return a stable, low-noise textual form for fingerprinting."""

    value = unicodedata.normalize("NFKC", str(text or "")).casefold()
    value = re.sub(r"https?://\S+", " ", value)
    value = re.sub(r"#[0-9]+|\b[0-9a-f]{7,40}\b", " ", value)
    value = re.sub(r"[\W_]+", " ", value, flags=re.UNICODE)
    return " ".join(value.split())


def tokens_for(text: Any) -> Tuple[str, ...]:
    """Tokenize text with light synonym folding."""

    normalized = normalize_text(text)
    tokens: List[str] = []
    for raw in _WORD_RE.findall(normalized):
        token = _SYNONYMS.get(raw, raw)
        if len(token) <= 1 or token in _STOPWORDS:
            continue
        tokens.append(token)
    return tuple(tokens)


def _item_text(item: Mapping[str, Any]) -> str:
    parts = []
    for key in ("title", "summary", "body", "text", "content", "observation", "message"):
        value = item.get(key)
        if value:
            parts.append(str(value))
    if not parts:
        parts.append(str(dict(item)))
    return " ".join(parts)


def semantic_fingerprint(item: Any, *, width: int = 12) -> str:
    """Build a stable semantic fingerprint for one feedback item.

    Fingerprints are based on normalized token frequency rather than raw text,
    so small wording differences collapse to the same key.
    """

    mapping = _as_mapping(item)
    tokens = tokens_for(_item_text(mapping))
    if not tokens:
        tokens = tokens_for(mapping.get("source", "") or mapping.get("kind", "") or "empty")

    counts = Counter(tokens)
    signature = " ".join(f"{token}:{counts[token]}" for token in sorted(counts))
    digest = hashlib.sha256(signature.encode("utf-8")).hexdigest()
    return digest[: max(6, int(width))]


def _heat(item: Mapping[str, Any]) -> float:
    for key in ("heat", "weight", "score", "count"):
        value = item.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return 1.0


def _first_cause(item: Mapping[str, Any]) -> str:
    for key in ("first_cause", "cause", "root_cause", "source", "kind", "channel"):
        value = item.get(key)
        if value:
            return str(value)
    return "unknown"


def _copy_item(item: Mapping[str, Any]) -> Dict[str, Any]:
    return dict(item)


def merge_duplicate(primary: MutableMapping[str, Any], duplicate: Mapping[str, Any]) -> MutableMapping[str, Any]:
    """Merge duplicate feedback into ``primary`` while preserving first cause."""

    primary["heat"] = float(primary.get("heat", 0.0) or 0.0) + _heat(duplicate)
    primary["duplicate_count"] = int(primary.get("duplicate_count", 1) or 1) + 1
    primary.setdefault("first_cause", _first_cause(primary))
    primary.setdefault("causes", [])
    causes = primary["causes"]
    if isinstance(causes, list):
        cause = _first_cause(duplicate)
        if cause not in causes:
            causes.append(cause)

    primary.setdefault("examples", [])
    examples = primary["examples"]
    if isinstance(examples, list) and len(examples) < 5:
        examples.append(_item_text(duplicate)[:240])

    return primary


def deduplicate_feedback(items: Iterable[Any]) -> List[Dict[str, Any]]:
    """Merge repeated feedback signals.

    Returned rows are sorted by heat descending, then by duplicate count.  Each
    row contains:

    - ``fingerprint``: semantic identity of the cluster
    - ``heat``: accumulated heat across duplicates
    - ``first_cause``: cause/source of the first observed item
    - ``duplicate_count``: number of merged items
    """

    clusters: Dict[str, Dict[str, Any]] = {}

    for raw in items:
        item = _as_mapping(raw)
        fingerprint = semantic_fingerprint(item)
        if fingerprint not in clusters:
            merged = _copy_item(item)
            merged["fingerprint"] = fingerprint
            merged["heat"] = _heat(item)
            merged["first_cause"] = _first_cause(item)
            merged["duplicate_count"] = 1
            merged["causes"] = [merged["first_cause"]]
            merged["examples"] = [_item_text(item)[:240]]
            clusters[fingerprint] = merged
            continue
        merge_duplicate(clusters[fingerprint], item)

    return sorted(
        clusters.values(),
        key=lambda row: (
            -float(row.get("heat", 0.0) or 0.0),
            -int(row.get("duplicate_count", 0) or 0),
            str(row.get("first_cause", "")),
        ),
    )


def dedup(items: Iterable[Any]) -> List[Dict[str, Any]]:
    """Compatibility alias for callers that prefer a shorter verb."""

    return deduplicate_feedback(items)


def fingerprints(items: Iterable[Any]) -> List[str]:
    """Return semantic fingerprints without merging the source items."""

    return [semantic_fingerprint(item) for item in items]


__all__ = [
    "dedup",
    "deduplicate_feedback",
    "fingerprints",
    "merge_duplicate",
    "normalize_text",
    "semantic_fingerprint",
    "tokens_for",
]
