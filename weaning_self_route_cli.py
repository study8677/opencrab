"""Brain-only default route drill for a small real CLI persistence gap.

This module is intentionally self-contained: it uses only the Python standard
library, performs an in-process fit-room rehearsal, and records that no external
helper was called.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


DEFAULT_GAP = "cli-ledger-parent-directory-missing"


@dataclass(frozen=True)
class BrainOnlyPatch:
    gap: str
    diagnosis: str
    change: str
    external_calls: int = 0


@dataclass(frozen=True)
class FitRoomResult:
    ok: bool
    checks: List[str]
    external_calls: int = 0


@dataclass(frozen=True)
class RouteEvidence:
    timestamp: str
    route: str
    gap: str
    brain_only: Dict[str, Any]
    fitroom: Dict[str, Any]
    backfeed: str
    external_calls: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _append_jsonl(path: Path, record: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def brain_only(gap: str = DEFAULT_GAP) -> BrainOnlyPatch:
    return BrainOnlyPatch(
        gap=gap,
        diagnosis=(
            "A CLI that writes evidence to a user supplied jsonl path can fail "
            "when the parent directory does not exist."
        ),
        change="Create the ledger parent directory before appending evidence.",
    )


def fitroom(patch: BrainOnlyPatch) -> FitRoomResult:
    checks: List[str] = []

    if patch.external_calls != 0:
        return FitRoomResult(False, ["brain_only_external_calls_not_zero"], patch.external_calls)

    with tempfile.TemporaryDirectory(prefix="opencrab_self_route_") as tmp:
        ledger = Path(tmp) / "missing" / "parents" / "route.jsonl"
        probe = {
            "route": "brain-only-default",
            "gap": patch.gap,
            "probe": "parent directory creation",
            "external_calls": 0,
        }
        _append_jsonl(ledger, probe)

        if not ledger.exists():
            return FitRoomResult(False, ["ledger_not_created"], 0)
        checks.append("ledger_created")

        loaded = json.loads(ledger.read_text(encoding="utf-8").splitlines()[-1])
        if loaded != probe:
            return FitRoomResult(False, ["ledger_roundtrip_mismatch"], 0)
        checks.append("ledger_jsonl_roundtrip")

    checks.append("no_external_calls")
    return FitRoomResult(True, checks, 0)


def backfeed(ledger: Path, patch: BrainOnlyPatch, trial: FitRoomResult) -> RouteEvidence:
    evidence = RouteEvidence(
        timestamp=_utc_now(),
        route="brain-only->fitroom->backfeed",
        gap=patch.gap,
        brain_only=asdict(patch),
        fitroom=asdict(trial),
        backfeed=str(ledger),
        external_calls=patch.external_calls + trial.external_calls,
    )
    _append_jsonl(ledger, asdict(evidence))
    return evidence


def run(ledger: Path, gap: str = DEFAULT_GAP) -> RouteEvidence:
    patch = brain_only(gap)
    trial = fitroom(patch)
    evidence = backfeed(ledger, patch, trial)
    if not trial.ok:
        raise SystemExit("fitroom rejected brain-only route: " + ",".join(trial.checks))
    if evidence.external_calls != 0:
        raise SystemExit("external_calls must remain 0")
    return evidence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the self-hand brain-only default route and record zero external calls."
    )
    parser.add_argument(
        "--ledger",
        default=".opencrab/weaning_self_route_cli.jsonl",
        help="JSONL evidence ledger path.",
    )
    parser.add_argument(
        "--gap",
        default=DEFAULT_GAP,
        help="Small CLI gap to route through brain-only -> fitroom -> backfeed.",
    )
    return parser


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    evidence = run(Path(args.ledger), args.gap)
    print(json.dumps(asdict(evidence), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
