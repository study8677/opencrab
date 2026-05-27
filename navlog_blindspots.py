"""Navigation log blind-spot map.

This module samples recent navigation logs, aligns them with an evidence
ledger, and surfaces themes that are repeatedly promised but rarely verified.

It is intentionally dependency-free so it can be used from tests, scripts, or
future long-term-memory jobs without coupling to a specific storage backend.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence


DEFAULT_SAMPLE_SIZE = 1024
DEFAULT_TOP_N = 3

PROMISE_HINTS = (
    "will",
    "todo",
    "next",
    "plan",
    "promise",
    "commit",
    "committed",
    "should",
    "must",
    "要",
    "将",
    "计划",
    "承诺",
    "推进",
    "下一步",
    "待",
)

VERIFY_HINTS = (
    "verified",
    "validated",
    "tested",
    "passed",
    "evidence",
    "proof",
    "measured",
    "done",
    "验",
    "验证",
    "证据",
    "通过",
    "完成",
    "实测",
    "复盘",
)

STOPWORDS = {
    "the",
    "and",
    "for",
    "that",
    "this",
    "with",
    "from",
    "into",
    "next",
    "will",
    "todo",
    "done",
    "plan",
    "must",
    "should",
    "have",
    "has",
    "had",
    "were",
    "been",
    "are",
    "was",
    "not",
    "but",
    "you",
    "our",
    "their",
    "about",
    "after",
    "before",
    "today",
    "tomorrow",
    "推进",
    "计划",
    "承诺",
    "下一步",
    "验证",
    "证据",
    "完成",
}


@dataclass(frozen=True)
class BlindspotTheme:
    """A theme that appears in promises more often than in verification."""

    theme: str
    promise_count: int
    verification_count: int
    promise_entries: int
    verification_entries: int
    blindspot_score: float
    sample_size: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _as_text(item: Any) -> str:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        for key in ("text", "content", "message", "summary", "note", "body"):
            value = item.get(key)
            if isinstance(value, str):
                return value
        return json.dumps(item, ensure_ascii=False, sort_keys=True)
    return str(item)


def _load_jsonl(path: str | Path) -> Iterator[Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if stripped:
                yield json.loads(stripped)


def _load_records(path: str | Path) -> list[Any]:
    source = Path(path)
    if source.suffix.lower() == ".jsonl":
        return list(_load_jsonl(source))
    text = source.read_text(encoding="utf-8").strip()
    if not text:
        return []
    data = json.loads(text)
    if isinstance(data, list):
        return data
    if isinstance(data, Mapping):
        for key in ("logs", "entries", "records", "items", "evidence"):
            value = data.get(key)
            if isinstance(value, list):
                return value
    return [data]


def _sample(items: Sequence[Any], sample_size: int, seed: int = 17) -> list[Any]:
    if sample_size <= 0:
        return []
    if len(items) <= sample_size:
        return list(items)
    rng = random.Random(seed)
    indexes = sorted(rng.sample(range(len(items)), sample_size))
    return [items[index] for index in indexes]


def _contains_any(text: str, hints: Iterable[str]) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in hints)


def _tokens(text: str) -> list[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z][a-z0-9_-]{2,}|[\u4e00-\u9fff]{2,}", lowered)
    return [word for word in words if word not in STOPWORDS and not word.isdigit()]


def _bigrams(tokens: Sequence[str]) -> Iterator[str]:
    for left, right in zip(tokens, tokens[1:]):
        if left != right:
            yield f"{left} {right}"


def _themes_for_text(text: str, max_themes: int = 8) -> set[str]:
    tokens = _tokens(text)
    counts = Counter(tokens)
    counts.update(_bigrams(tokens))
    return {theme for theme, _ in counts.most_common(max_themes)}


def _collect_promises(logs: Sequence[Any]) -> tuple[Counter[str], Counter[str]]:
    theme_counts: Counter[str] = Counter()
    entry_counts: Counter[str] = Counter()
    for item in logs:
        text = _as_text(item)
        if not _contains_any(text, PROMISE_HINTS):
            continue
        themes = _themes_for_text(text)
        theme_counts.update(themes)
        for theme in themes:
            entry_counts[theme] += 1
    return theme_counts, entry_counts


def _collect_verifications(records: Sequence[Any]) -> tuple[Counter[str], Counter[str]]:
    theme_counts: Counter[str] = Counter()
    entry_counts: Counter[str] = Counter()
    for item in records:
        text = _as_text(item)
        if not _contains_any(text, VERIFY_HINTS):
            continue
        themes = _themes_for_text(text)
        theme_counts.update(themes)
        for theme in themes:
            entry_counts[theme] += 1
    return theme_counts, entry_counts


def _score(promise_count: int, verification_count: int, sample_size: int) -> float:
    scarcity = 1.0 / (1.0 + verification_count)
    recurrence = math.log1p(promise_count)
    sample_weight = math.log1p(max(sample_size, 1))
    return round(recurrence * scarcity * sample_weight, 6)


def build_blindspot_map(
    logs: Sequence[Any],
    evidence_records: Sequence[Any],
    *,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    top_n: int = DEFAULT_TOP_N,
    seed: int = 17,
) -> list[BlindspotTheme]:
    """Return the top themes promised in logs but under-verified in evidence.

    Args:
        logs: Navigation-log entries as strings or mappings.
        evidence_records: Evidence-ledger entries as strings or mappings.
        sample_size: Maximum number of logs to inspect. Defaults to 1024.
        top_n: Number of blind spots to return. Defaults to 3.
        seed: Deterministic sample seed for reproducible comparisons.
    """

    sampled_logs = _sample(list(logs), sample_size, seed)
    promise_counts, promise_entries = _collect_promises(sampled_logs)
    verification_counts, verification_entries = _collect_verifications(list(evidence_records))

    candidates: list[BlindspotTheme] = []
    for theme, promise_count in promise_counts.items():
        verification_count = verification_counts.get(theme, 0)
        if promise_count < 2:
            continue
        if verification_count >= promise_count:
            continue
        candidates.append(
            BlindspotTheme(
                theme=theme,
                promise_count=promise_count,
                verification_count=verification_count,
                promise_entries=promise_entries.get(theme, 0),
                verification_entries=verification_entries.get(theme, 0),
                blindspot_score=_score(promise_count, verification_count, len(sampled_logs)),
                sample_size=len(sampled_logs),
            )
        )

    candidates.sort(
        key=lambda item: (
            item.blindspot_score,
            item.promise_count - item.verification_count,
            item.promise_count,
            item.theme,
        ),
        reverse=True,
    )
    return candidates[: max(top_n, 0)]


def render_report(themes: Sequence[BlindspotTheme]) -> str:
    if not themes:
        return "No repeated promise / weak verification blind spots found."
    lines = ["Navigation log blind-spot map:"]
    for index, theme in enumerate(themes, 1):
        lines.append(
            f"{index}. {theme.theme} — promises={theme.promise_count}, "
            f"verified={theme.verification_count}, score={theme.blindspot_score}"
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a navigation-log blind-spot map.")
    parser.add_argument("logs", help="Path to log JSON/JSONL records.")
    parser.add_argument("evidence", help="Path to evidence-ledger JSON/JSONL records.")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = parser.parse_args(argv)

    themes = build_blindspot_map(
        _load_records(args.logs),
        _load_records(args.evidence),
        sample_size=args.sample_size,
        top_n=args.top_n,
        seed=args.seed,
    )
    if args.json:
        print(json.dumps([theme.to_dict() for theme in themes], ensure_ascii=False, indent=2))
    else:
        print(render_report(themes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
