"""Evidence fragility auto-repair queue.

This module turns noisy validation failures into a small, actionable repair
queue.  It clusters the most brittle verification commands, ranks the clusters
by trust impact, and proposes the minimal rerun path needed to confirm a fix.

The functions are deliberately dependency-free so they can be used from tests,
release rehearsals, or future CLI glue without pulling in the rest of crab.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import re


_PATH_RE = re.compile(r"([A-Za-z0-9_./\\-]+\.py)(?::\d+)?")
_FLAG_VALUE_RE = re.compile(r"(--[A-Za-z0-9][A-Za-z0-9_-]*)(?:=|\s+)([^-\s][^\s]*)")


@dataclass(frozen=True)
class VerificationFailure:
    """One observed broken verification command."""

    command: str
    reason: str = ""
    count: int = 1
    evidence_weight: float = 1.0
    last_seen: str = ""

    def normalized_command(self) -> str:
        return normalize_command(self.command)


@dataclass(frozen=True)
class RepairCandidate:
    """A clustered brittle point and its smallest useful rerun path."""

    key: str
    commands: Tuple[str, ...]
    reasons: Tuple[str, ...]
    touched_paths: Tuple[str, ...]
    failures: int
    evidence_weight: float
    trust_impact: float
    minimal_rerun_path: Tuple[str, ...]
    repair_hint: str
    labels: Tuple[str, ...] = field(default_factory=tuple)


def normalize_command(command: str) -> str:
    """Normalize a validation command enough to cluster recurring failures."""

    text = " ".join(str(command or "").strip().split())
    text = re.sub(r"\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+-]+)?\b", "<date>", text)
    text = re.sub(r"\b[0-9a-f]{7,40}\b", "<sha>", text, flags=re.IGNORECASE)
    text = re.sub(r"\b\d+\b", "<n>", text)

    def _flag_repl(match: re.Match[str]) -> str:
        flag, value = match.group(1), match.group(2)
        if value.endswith(".py") or "/" in value or "\\" in value:
            return f"{flag}=<path>"
        return f"{flag}=<value>"

    text = _FLAG_VALUE_RE.sub(_flag_repl, text)
    return text


def extract_paths(command: str, reason: str = "") -> Tuple[str, ...]:
    """Extract python file paths mentioned by a command or its failure reason."""

    found = []
    for source in (command or "", reason or ""):
        for match in _PATH_RE.finditer(source):
            path = match.group(1).replace("\\", "/")
            if path not in found:
                found.append(path)
    return tuple(found)


def cluster_key(command: str, reason: str = "") -> str:
    """Return the stable key used to group equivalent brittle commands."""

    normalized = normalize_command(command)
    paths = extract_paths(command, reason)
    if paths:
        root = ",".join(paths[:3])
        return f"path:{root}|cmd:{normalized}"
    tokens = normalized.split()
    return "cmd:" + " ".join(tokens[:5])


def _as_failure(item: object) -> VerificationFailure:
    if isinstance(item, VerificationFailure):
        return item
    if isinstance(item, Mapping):
        return VerificationFailure(
            command=str(item.get("command", "")),
            reason=str(item.get("reason", "")),
            count=max(1, int(item.get("count", 1) or 1)),
            evidence_weight=float(item.get("evidence_weight", item.get("weight", 1.0)) or 1.0),
            last_seen=str(item.get("last_seen", "")),
        )
    if isinstance(item, (list, tuple)):
        command = str(item[0]) if len(item) > 0 else ""
        reason = str(item[1]) if len(item) > 1 else ""
        count = max(1, int(item[2])) if len(item) > 2 else 1
        return VerificationFailure(command=command, reason=reason, count=count)
    return VerificationFailure(command=str(item))


def _dedupe_keep_order(values: Iterable[str]) -> Tuple[str, ...]:
    seen = set()
    kept = []
    for value in values:
        value = str(value).strip()
        if value and value not in seen:
            kept.append(value)
            seen.add(value)
    return tuple(kept)


def _repair_hint(commands: Sequence[str], reasons: Sequence[str], paths: Sequence[str]) -> str:
    joined = " ".join([*commands, *reasons]).lower()
    if "import" in joined or "modulenotfound" in joined:
        return "repair import/package boundary first, then rerun the clustered command"
    if "syntax" in joined or "py_compile" in joined:
        return "repair syntax/compile breakage before broader validation"
    if "assert" in joined or "expected" in joined:
        return "repair behavioral regression covered by the narrowest failing test"
    if paths:
        return f"inspect shared evidence path {paths[0]} and rerun the minimal path"
    return "rerun the representative command after the smallest plausible fix"


def build_repair_queue(
    failures: Iterable[object],
    *,
    max_reruns_per_candidate: int = 3,
    trust_floor: float = 0.0,
) -> List[RepairCandidate]:
    """Cluster failures into ranked repair candidates.

    Args:
        failures: VerificationFailure objects, mappings with at least
            ``command``, or simple tuples like ``(command, reason, count)``.
        max_reruns_per_candidate: Maximum commands kept in each minimal rerun
            path.  The first command is always the most frequent representative.
        trust_floor: Drop candidates below this computed trust impact.

    Returns:
        RepairCandidate list sorted by descending trust impact.
    """

    buckets: Dict[str, List[VerificationFailure]] = {}
    for raw in failures:
        failure = _as_failure(raw)
        if not failure.command.strip():
            continue
        buckets.setdefault(cluster_key(failure.command, failure.reason), []).append(failure)

    candidates: List[RepairCandidate] = []
    for key, group in buckets.items():
        command_counts: Dict[str, int] = {}
        reason_values: List[str] = []
        path_values: List[str] = []
        total_failures = 0
        total_weight = 0.0

        for failure in group:
            normalized = failure.normalized_command()
            command_counts[normalized] = command_counts.get(normalized, 0) + failure.count
            if failure.reason:
                reason_values.append(failure.reason)
            path_values.extend(extract_paths(failure.command, failure.reason))
            total_failures += failure.count
            total_weight += failure.evidence_weight * failure.count

        ranked_commands = sorted(command_counts, key=lambda cmd: (-command_counts[cmd], cmd))
        commands = tuple(ranked_commands)
        reasons = _dedupe_keep_order(reason_values)
        paths = _dedupe_keep_order(path_values)
        trust_impact = float(total_failures) * max(total_weight, 1.0)

        if trust_impact < trust_floor:
            continue

        minimal = tuple(ranked_commands[: max(1, int(max_reruns_per_candidate))])
        labels = []
        if total_failures >= 3:
            labels.append("recurring")
        if len(paths) == 1:
            labels.append("single-path")
        elif len(paths) > 1:
            labels.append("cross-path")
        if any("py_compile" in cmd for cmd in ranked_commands):
            labels.append("compile-gate")

        candidates.append(
            RepairCandidate(
                key=key,
                commands=commands,
                reasons=reasons,
                touched_paths=paths,
                failures=total_failures,
                evidence_weight=round(total_weight, 3),
                trust_impact=round(trust_impact, 3),
                minimal_rerun_path=minimal,
                repair_hint=_repair_hint(commands, reasons, paths),
                labels=tuple(labels),
            )
        )

    return sorted(
        candidates,
        key=lambda item: (-item.trust_impact, -item.failures, item.key),
    )


def summarize_repair_queue(candidates: Sequence[RepairCandidate], limit: Optional[int] = None) -> str:
    """Render a compact human-readable repair queue."""

    rows = []
    selected = candidates if limit is None else candidates[: max(0, int(limit))]
    for index, candidate in enumerate(selected, 1):
        rerun = " && ".join(candidate.minimal_rerun_path)
        paths = ", ".join(candidate.touched_paths) or "-"
        labels = ",".join(candidate.labels) or "-"
        rows.append(
            f"{index}. impact={candidate.trust_impact:g} failures={candidate.failures} "
            f"labels={labels} paths={paths}\n"
            f"   rerun: {rerun}\n"
            f"   hint: {candidate.repair_hint}"
        )
    return "\n".join(rows)


__all__ = [
    "RepairCandidate",
    "VerificationFailure",
    "build_repair_queue",
    "cluster_key",
    "extract_paths",
    "normalize_command",
    "summarize_repair_queue",
]
