"""Evidence fragility map for hot capability evidence.

This module builds a small, offline-friendly report that answers:
- Which capability evidence items are currently the hottest?
- Which ones depend on a single brittle verifier?
- What offline command can re-check the evidence?
- What should happen when the evidence path fails?

It intentionally uses only the Python standard library so it remains usable
during dependency outages.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


DEFAULT_SOURCES = (
    "evidence.jsonl",
    "evidence.log",
    "usageheat.jsonl",
    "navlog.jsonl",
    "changelog.jsonl",
)


@dataclass(frozen=True)
class FragilityItem:
    """One hot evidence item with its failure plan."""

    rank: int
    capability: str
    evidence: str
    heat: float
    verifier: str
    single_point_dependency: str
    offline_alternative_command: str
    failure_disposition: str
    source: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "capability": self.capability,
            "evidence": self.evidence,
            "heat": self.heat,
            "verifier": self.verifier,
            "single_point_dependency": self.single_point_dependency,
            "offline_alternative_command": self.offline_alternative_command,
            "failure_disposition": self.failure_disposition,
            "source": self.source,
            "detail": self.detail,
        }


def _coerce_float(value: Any, default: float = 1.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _first_text(record: dict[str, Any], keys: Iterable[str], default: str) -> str:
    for key in keys:
        value = record.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return default


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists() or not path.is_file():
        return rows
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, 1):
            text = line.strip()
            if not text:
                continue
            try:
                record = json.loads(text)
            except json.JSONDecodeError:
                record = {"evidence": text, "line": line_number}
            if isinstance(record, dict):
                record.setdefault("_source", str(path))
                record.setdefault("_line", line_number)
                rows.append(record)
    return rows


def load_records(paths: Iterable[str | os.PathLike[str]] = DEFAULT_SOURCES) -> list[dict[str, Any]]:
    """Load candidate evidence records from existing JSONL-ish sources."""

    records: list[dict[str, Any]] = []
    for raw_path in paths:
        records.extend(_load_jsonl(Path(raw_path)))
    return records


def _heat(record: dict[str, Any]) -> float:
    explicit = record.get("heat", record.get("usage_heat", record.get("score")))
    if explicit is not None:
        return _coerce_float(explicit)

    touches = _coerce_float(record.get("touches", record.get("count")), 0.0)
    recency = _coerce_float(record.get("recency", record.get("freshness")), 0.0)
    failures = _coerce_float(record.get("failures", record.get("flake_count")), 0.0)
    return max(1.0, touches + recency + failures * 2.0)


def _single_point(record: dict[str, Any], verifier: str) -> str:
    declared = _first_text(
        record,
        ("single_point_dependency", "dependency", "external_dependency", "tool", "service"),
        "",
    )
    if declared:
        return declared
    if verifier and verifier not in {"python -m py_compile", "import"}:
        return verifier
    return "only one recorded verifier or no independent replay path"


def _offline_command(record: dict[str, Any], capability: str, evidence: str) -> str:
    command = _first_text(
        record,
        ("offline_alternative_command", "offline_command", "replay_command", "command"),
        "",
    )
    if command:
        return command

    module = _first_text(record, ("module", "file", "path"), "")
    if module.endswith(".py"):
        return f"{sys.executable} -m py_compile {module}"
    if module:
        dotted = module[:-3] if module.endswith(".py") else module
        dotted = dotted.replace("/", ".").replace("\\", ".").strip(".")
        return f"{sys.executable} -c \"import {dotted}\""

    token = capability or evidence
    safe = "".join(ch for ch in token.lower() if ch.isalnum() or ch in "_- ")[:48].strip()
    return f"{sys.executable} -m regression --grep {json.dumps(safe or 'evidence')}"


def _failure_disposition(record: dict[str, Any], dependency: str) -> str:
    disposition = _first_text(
        record,
        ("failure_disposition", "fallback", "remediation", "on_failure"),
        "",
    )
    if disposition:
        return disposition
    return (
        "mark evidence degraded, quarantine dependent claim, run offline alternative, "
        f"and require a second verifier before trusting {dependency}"
    )


def build_fragility_map(records: Iterable[dict[str, Any]], limit: int = 10) -> list[FragilityItem]:
    """Return the hottest evidence items annotated with fragility handling."""

    ordered = sorted(records, key=_heat, reverse=True)[: max(0, limit)]
    items: list[FragilityItem] = []
    for index, record in enumerate(ordered, 1):
        capability = _first_text(record, ("capability", "skill", "name", "area"), "unknown-capability")
        evidence = _first_text(record, ("evidence", "claim", "summary", "title", "message"), capability)
        verifier = _first_text(record, ("verifier", "check", "test", "gate"), "unrecorded verifier")
        dependency = _single_point(record, verifier)
        command = _offline_command(record, capability, evidence)
        items.append(
            FragilityItem(
                rank=index,
                capability=capability,
                evidence=evidence,
                heat=_heat(record),
                verifier=verifier,
                single_point_dependency=dependency,
                offline_alternative_command=command,
                failure_disposition=_failure_disposition(record, dependency),
                source=_first_text(record, ("_source", "source"), ""),
                detail=_first_text(record, ("detail", "notes", "reason"), ""),
            )
        )
    return items


def render_markdown(items: Iterable[FragilityItem]) -> str:
    """Render a compact human-readable fragility map."""

    lines = [
        "# Evidence Fragility Map",
        "",
        "| # | capability | heat | single point dependency | offline alternative | failure disposition |",
        "|---:|---|---:|---|---|---|",
    ]
    for item in items:
        lines.append(
            "| {rank} | {capability} | {heat:.2f} | {dependency} | `{command}` | {failure} |".format(
                rank=item.rank,
                capability=_cell(item.capability),
                heat=item.heat,
                dependency=_cell(item.single_point_dependency),
                command=item.offline_alternative_command.replace("`", "'"),
                failure=_cell(item.failure_disposition),
            )
        )
    return "\n".join(lines) + "\n"


def _cell(value: str) -> str:
    return str(value).replace("|", "\\|").replace("\n", " ")


def verify_offline_commands(items: Iterable[FragilityItem], timeout: float = 20.0) -> list[dict[str, Any]]:
    """Best-effort execution of offline alternatives.

    Commands are run through the platform shell because the saved replay command
    is evidence metadata. The timeout is deliberately short so a broken verifier
    cannot stall the map.
    """

    results: list[dict[str, Any]] = []
    for item in items:
        try:
            completed = subprocess.run(
                item.offline_alternative_command,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            ok = completed.returncode == 0
            output = (completed.stdout or completed.stderr or "").strip()[:500]
            results.append({"rank": item.rank, "ok": ok, "returncode": completed.returncode, "output": output})
        except Exception as exc:  # pragma: no cover - defensive CLI path
            results.append({"rank": item.rank, "ok": False, "returncode": None, "output": repr(exc)})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the hot-10 evidence fragility map.")
    parser.add_argument("sources", nargs="*", default=list(DEFAULT_SOURCES), help="JSONL evidence sources")
    parser.add_argument("--limit", type=int, default=10, help="number of hot evidence items")
    parser.add_argument("--json", action="store_true", help="emit JSON instead of markdown")
    parser.add_argument("--verify", action="store_true", help="run offline alternative commands")
    args = parser.parse_args(argv)

    records = load_records(args.sources)
    items = build_fragility_map(records, args.limit)

    if args.verify:
        payload: Any = {"items": [item.as_dict() for item in items], "verification": verify_offline_commands(items)}
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    elif args.json:
        print(json.dumps([item.as_dict() for item in items], ensure_ascii=False, indent=2))
    else:
        print(render_markdown(items), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
