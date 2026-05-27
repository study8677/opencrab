"""Low-heat, low-trust organ retirement probe.

This module implements a conservative retirement drill:

* choose exactly three retirement candidates;
* require a runnable replacement path for each candidate;
* retire at most one candidate per run;
* never delete files by itself.

The goal is to provide empirical evidence before pruning old, unused organs.
It is intentionally dependency-light so it can be compiled and imported even in
minimal environments.
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path
from typing import Callable, Iterable, Sequence


@dataclass(frozen=True)
class RetirementCandidate:
    """A candidate organ and the path that should replace it."""

    organ: str
    replacement: str
    reason: str


@dataclass(frozen=True)
class RetirementProbeResult:
    """Outcome for one candidate."""

    candidate: RetirementCandidate
    replacement_imported: bool
    replacement_selfcheck: bool
    passed: bool
    detail: str


@dataclass(frozen=True)
class RetirementDecision:
    """One-run retirement decision.

    retired is None unless exactly one candidate has a verified replacement
    path.  This conservative shape prevents batch pruning.
    """

    candidates_checked: int
    retired: str | None
    replacement: str | None
    results: tuple[RetirementProbeResult, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "candidates_checked": self.candidates_checked,
            "retired": self.retired,
            "replacement": self.replacement,
            "results": [
                {
                    "organ": result.candidate.organ,
                    "replacement": result.candidate.replacement,
                    "reason": result.candidate.reason,
                    "replacement_imported": result.replacement_imported,
                    "replacement_selfcheck": result.replacement_selfcheck,
                    "passed": result.passed,
                    "detail": result.detail,
                }
                for result in self.results
            ],
        }


DEFAULT_CANDIDATES: tuple[RetirementCandidate, ...] = (
    RetirementCandidate(
        organ="autonomy_meter",
        replacement="autonomy_calibration",
        reason="meter-style reporting appears superseded by calibrated autonomy evidence",
    ),
    RetirementCandidate(
        organ="readpack_astlocator",
        replacement="astlocator",
        reason="specialized readpack locator should defer to the general locator if viable",
    ),
    RetirementCandidate(
        organ="weaning_docfix_default_route",
        replacement="weaning_self_route_cli",
        reason="default docfix route is a narrow old claw if self-route can run",
    ),
)


def _module_selfcheck(module: object) -> tuple[bool, str]:
    """Run a tiny non-invasive replacement check.

    If a module exposes a conventional lightweight check function, use it.
    Otherwise successful import is accepted as the runnable path evidence.
    """

    for name in ("selfcheck", "smoke", "healthcheck"):
        check = getattr(module, name, None)
        if callable(check):
            try:
                value = check()
            except Exception as exc:  # pragma: no cover - defensive evidence
                return False, f"{name} raised {exc.__class__.__name__}: {exc}"
            if value is False:
                return False, f"{name} returned False"
            return True, f"{name} passed"
    return True, "import passed; no explicit selfcheck exposed"


def probe_candidate(candidate: RetirementCandidate) -> RetirementProbeResult:
    """Verify that a candidate's replacement path can actually run."""

    try:
        module = importlib.import_module(candidate.replacement)
    except Exception as exc:
        return RetirementProbeResult(
            candidate=candidate,
            replacement_imported=False,
            replacement_selfcheck=False,
            passed=False,
            detail=f"replacement import failed: {exc.__class__.__name__}: {exc}",
        )

    ok, detail = _module_selfcheck(module)
    return RetirementProbeResult(
        candidate=candidate,
        replacement_imported=True,
        replacement_selfcheck=ok,
        passed=ok,
        detail=detail,
    )


def run_retirement_probe(
    candidates: Sequence[RetirementCandidate] = DEFAULT_CANDIDATES,
) -> RetirementDecision:
    """Run the conservative three-candidate drill.

    Exactly three candidates must be supplied.  The function checks all three,
    then selects only the first verified candidate for retirement evidence.
    It does not remove files or mutate source code.
    """

    if len(candidates) != 3:
        raise ValueError("low-heat retirement drill requires exactly 3 candidates")

    results = tuple(probe_candidate(candidate) for candidate in candidates)
    verified = [result for result in results if result.passed]
    retired = verified[0].candidate.organ if verified else None
    replacement = verified[0].candidate.replacement if verified else None
    return RetirementDecision(
        candidates_checked=len(results),
        retired=retired,
        replacement=replacement,
        results=results,
    )


def write_decision(
    path: str | Path = "lowheat_lowtrust_retirement_report.json",
    candidates: Sequence[RetirementCandidate] = DEFAULT_CANDIDATES,
) -> RetirementDecision:
    """Run the drill and write machine-readable evidence."""

    decision = run_retirement_probe(candidates)
    Path(path).write_text(
        json.dumps(decision.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return decision


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entry point.

    With no arguments, prints the one-run decision.  With one argument, writes
    the same decision to that path.
    """

    args = list(argv or [])
    if len(args) > 1:
        raise SystemExit("usage: python -m lowheat_lowtrust_retirement [report.json]")

    if args:
        decision = write_decision(args[0])
    else:
        decision = run_retirement_probe()

    print(json.dumps(decision.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
