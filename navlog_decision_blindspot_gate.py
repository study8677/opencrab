"""Decision blindspot rumination gate for planner prefaces.

This module mines recent navigation logs for decisions that looked confident
but paid off poorly, then turns the recurring patterns into three compact
counterexamples that can be prepended to a planner prompt.

It is intentionally dependency-free and tolerant of loose log formats:
JSONL, JSON arrays, JSON objects, and plain text snippets are all accepted.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


_CONFIDENCE_KEYS = (
    "confidence",
    "conf",
    "certainty",
    "self_confidence",
    "decision_confidence",
    "planner_confidence",
)

_BENEFIT_KEYS = (
    "benefit",
    "value",
    "reward",
    "gain",
    "impact",
    "outcome_score",
    "realized_value",
    "roi",
    "payoff",
)

_DECISION_KEYS = (
    "decision",
    "choice",
    "action",
    "plan",
    "move",
    "route",
    "summary",
    "title",
)

_CONTEXT_KEYS = (
    "context",
    "why",
    "rationale",
    "reason",
    "assumption",
    "hypothesis",
    "intent",
)


@dataclass(frozen=True)
class BlindspotDecision:
    """A high-confidence decision with weak realized benefit."""

    decision: str
    confidence: float
    benefit: float
    context: str = ""
    source: str = ""

    @property
    def gap(self) -> float:
        return self.confidence - self.benefit


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str):
        text = value.strip().rstrip("%")
        try:
            number = float(text)
        except ValueError:
            return None
        if value.strip().endswith("%"):
            number = number / 100.0
    else:
        return None

    if number > 1.0 and number <= 100.0:
        number = number / 100.0
    if number < -1.0 or number > 1.0:
        return None
    return number


def _first_text(record: Mapping[str, Any], keys: Sequence[str]) -> str:
    for key in keys:
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return " ".join(value.split())
    return ""


def _flatten_records(obj: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(obj, Mapping):
        yielded_child = False
        for key in ("entries", "logs", "decisions", "items", "records"):
            child = obj.get(key)
            if isinstance(child, list):
                yielded_child = True
                for item in child:
                    yield from _flatten_records(item)
        if not yielded_child:
            yield obj
    elif isinstance(obj, list):
        for item in obj:
            yield from _flatten_records(item)


def _parse_text_record(text: str) -> Optional[Dict[str, Any]]:
    compact = " ".join(text.split())
    if not compact:
        return None

    conf_match = re.search(r"(?:confidence|conf|certainty)\s*[:=]\s*([0-9]+(?:\.[0-9]+)?%?)", compact, re.I)
    benefit_match = re.search(
        r"(?:benefit|value|reward|gain|impact|roi|payoff)\s*[:=]\s*(-?[0-9]+(?:\.[0-9]+)?%?)",
        compact,
        re.I,
    )
    if not conf_match or not benefit_match:
        return None

    decision_match = re.search(r"(?:decision|choice|action|plan|move)\s*[:=]\s*([^.;]+)", compact, re.I)
    decision = decision_match.group(1).strip() if decision_match else compact[:160]
    return {
        "decision": decision,
        "confidence": conf_match.group(1),
        "benefit": benefit_match.group(1),
        "context": compact[:240],
    }


def _records_from_text(text: str) -> Iterable[Mapping[str, Any]]:
    stripped = text.strip()
    if not stripped:
        return []

    try:
        parsed = json.loads(stripped)
    except Exception:
        parsed = None
    if parsed is not None:
        return list(_flatten_records(parsed))

    records: List[Mapping[str, Any]] = []
    for line in stripped.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            parsed_line = json.loads(line)
        except Exception:
            parsed_line = None
        if parsed_line is not None:
            records.extend(_flatten_records(parsed_line))
            continue
        text_record = _parse_text_record(line)
        if text_record:
            records.append(text_record)
    return records


def load_recent_navlog_records(paths: Sequence[str], limit: int = 50) -> List[Mapping[str, Any]]:
    """Load records from the newest navlog files, newest paths first.

    Missing files are ignored so callers can pass glob results without a
    preflight step.
    """

    existing = [path for path in paths if os.path.exists(path)]
    newest = sorted(existing, key=lambda path: os.path.getmtime(path), reverse=True)[:limit]

    records: List[Mapping[str, Any]] = []
    for path in newest:
        try:
            with open(path, "r", encoding="utf-8") as handle:
                text = handle.read()
        except OSError:
            continue
        for record in _records_from_text(text):
            copy = dict(record)
            copy.setdefault("_source", path)
            records.append(copy)
    return records


def extract_blindspot_decisions(
    records: Iterable[Mapping[str, Any]],
    high_confidence: float = 0.75,
    low_benefit: float = 0.25,
) -> List[BlindspotDecision]:
    """Return high-confidence / low-benefit decisions sorted by regret gap."""

    blindspots: List[BlindspotDecision] = []
    for record in records:
        confidence = None
        benefit = None

        for key in _CONFIDENCE_KEYS:
            confidence = _as_float(record.get(key))
            if confidence is not None:
                break
        for key in _BENEFIT_KEYS:
            benefit = _as_float(record.get(key))
            if benefit is not None:
                break

        if confidence is None or benefit is None:
            continue
        if confidence < high_confidence or benefit > low_benefit:
            continue

        decision = _first_text(record, _DECISION_KEYS) or "unnamed familiar-looking decision"
        context = _first_text(record, _CONTEXT_KEYS)
        source = str(record.get("_source", record.get("source", "")))
        blindspots.append(
            BlindspotDecision(
                decision=decision,
                confidence=confidence,
                benefit=benefit,
                context=context,
                source=source,
            )
        )

    return sorted(blindspots, key=lambda item: (item.gap, item.confidence), reverse=True)


def _theme(decision: BlindspotDecision) -> str:
    text = (decision.decision + " " + decision.context).lower()
    themes: Tuple[Tuple[str, Tuple[str, ...]], ...] = (
        ("熟悉路径替代验证", ("routine", "familiar", "惯例", "熟悉", "默认", "照旧", "复用")),
        ("速度压过证据", ("fast", "quick", "rush", "加速", "快速", "省事", "立刻")),
        ("局部修补冒充收益", ("patch", "fix", "hotfix", "修补", "补丁", "小改", "微调")),
        ("高把握掩盖外部依赖", ("external", "dependency", "api", "依赖", "外部", "接口")),
        ("计划自信早于验收", ("test", "verify", "acceptance", "验收", "验证", "测试")),
    )
    for label, needles in themes:
        if any(needle in text for needle in needles):
            return label
    return "高信心低收益错路"


def generate_planner_counterexamples(
    blindspots: Sequence[BlindspotDecision],
    count: int = 3,
) -> List[str]:
    """Create compact planner preface counterexamples."""

    selected: List[BlindspotDecision] = []
    seen_themes = set()

    for item in blindspots:
        label = _theme(item)
        if label in seen_themes and len(blindspots) >= count:
            continue
        selected.append(item)
        seen_themes.add(label)
        if len(selected) >= count:
            break

    for item in blindspots:
        if len(selected) >= count:
            break
        if item not in selected:
            selected.append(item)

    counterexamples: List[str] = []
    for index, item in enumerate(selected[:count], 1):
        label = _theme(item)
        decision = item.decision[:120]
        context = item.context[:100]
        context_part = ("；当时理由：" + context) if context else ""
        counterexamples.append(
            (
                f"{index}. 反例[{label}]：曾以{item.confidence:.0%}把握选择“{decision}”，"
                f"实际收益仅{item.benefit:.0%}{context_part}。planner先问："
                "这次是否只是熟悉、快速或局部顺手，而缺少可验收的新证据？"
            )
        )

    while len(counterexamples) < count:
        index = len(counterexamples) + 1
        counterexamples.append(
            f"{index}. 反例[样本不足]：近50篇日志中可解析的高信心低收益样本不足；"
            "planner先补证据口径，不要把没有反例误判为没有盲点。"
        )

    return counterexamples


def planner_blindspot_preface(
    navlog_paths: Sequence[str],
    limit: int = 50,
    high_confidence: float = 0.75,
    low_benefit: float = 0.25,
) -> str:
    """Build the three-line preface for a planner from recent navlogs."""

    records = load_recent_navlog_records(navlog_paths, limit=limit)
    blindspots = extract_blindspot_decisions(
        records,
        high_confidence=high_confidence,
        low_benefit=low_benefit,
    )
    lines = generate_planner_counterexamples(blindspots, count=3)
    return "决策盲点反刍闸：先读3条高信心低收益反例，少走熟悉错路。\n" + "\n".join(lines)


__all__ = [
    "BlindspotDecision",
    "extract_blindspot_decisions",
    "generate_planner_counterexamples",
    "load_recent_navlog_records",
    "planner_blindspot_preface",
]
