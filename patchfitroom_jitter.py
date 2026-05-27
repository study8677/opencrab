"""Jitter isolation helpers for patchfitroom-style verification.

The goal is to avoid rejecting a good patch because a single validation run was
polluted by environmental noise.  Call ``isolate_jitter`` with a verification
callable; it will automatically resample suspicious failures and classify the
outcome as a pass, an occasional/flaky failure, or a true regression.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Mapping, Optional


PASS = "pass"
OCCASIONAL = "occasional"
TRUE_REGRESSION = "true_regression"


@dataclass(frozen=True)
class VerificationAttempt:
    """One verification sample normalized into a small stable shape."""

    ok: bool
    detail: str = ""
    raw: Any = None


@dataclass(frozen=True)
class JitterVerdict:
    """Final jitter-aware verdict for a patch verification."""

    status: str
    ok: bool
    attempts: List[VerificationAttempt] = field(default_factory=list)
    annotation: str = ""
    resampled: bool = False

    @property
    def flaky(self) -> bool:
        return self.status == OCCASIONAL

    @property
    def true_regression(self) -> bool:
        return self.status == TRUE_REGRESSION


def _normalize_attempt(result: Any) -> VerificationAttempt:
    """Accept common verifier return shapes and normalize them."""

    if isinstance(result, VerificationAttempt):
        return result

    if isinstance(result, Mapping):
        ok = bool(result.get("ok", result.get("passed", result.get("pass", False))))
        detail = str(
            result.get(
                "detail",
                result.get("reason", result.get("message", result.get("error", ""))),
            )
        )
        return VerificationAttempt(ok=ok, detail=detail, raw=result)

    if isinstance(result, tuple) and result:
        ok = bool(result[0])
        detail = str(result[1]) if len(result) > 1 else ""
        return VerificationAttempt(ok=ok, detail=detail, raw=result)

    return VerificationAttempt(ok=bool(result), detail="", raw=result)


def isolate_jitter(
    verify: Callable[[], Any],
    *,
    max_resamples: int = 3,
    stable_failures: int = 2,
) -> JitterVerdict:
    """Run verification with failure resampling and classify the outcome.

    A first-pass success is accepted immediately.  A first-pass failure is
    resampled up to ``max_resamples`` times:

    * any later success means the failure was occasional/flaky;
    * enough repeated failures means true regression;
    * exhausted failures are conservatively treated as true regression.

    ``stable_failures`` counts total failing samples, including the first one.
    """

    if max_resamples < 0:
        raise ValueError("max_resamples must be >= 0")
    if stable_failures < 1:
        raise ValueError("stable_failures must be >= 1")

    attempts: List[VerificationAttempt] = [_normalize_attempt(verify())]
    if attempts[0].ok:
        return JitterVerdict(
            status=PASS,
            ok=True,
            attempts=attempts,
            annotation="verification passed on first sample",
            resampled=False,
        )

    while len(attempts) <= max_resamples:
        failures = sum(1 for attempt in attempts if not attempt.ok)
        if failures >= stable_failures:
            return JitterVerdict(
                status=TRUE_REGRESSION,
                ok=False,
                attempts=attempts,
                annotation="failure reproduced across resample window",
                resampled=len(attempts) > 1,
            )

        attempts.append(_normalize_attempt(verify()))
        if attempts[-1].ok:
            return JitterVerdict(
                status=OCCASIONAL,
                ok=True,
                attempts=attempts,
                annotation="initial failure did not reproduce; marked occasional",
                resampled=True,
            )

    return JitterVerdict(
        status=TRUE_REGRESSION,
        ok=False,
        attempts=attempts,
        annotation="failure persisted until resample budget was exhausted",
        resampled=len(attempts) > 1,
    )


def annotate_result(verdict: JitterVerdict) -> Dict[str, Any]:
    """Return a JSON-friendly annotation for patchfitroom logs."""

    return {
        "ok": verdict.ok,
        "status": verdict.status,
        "flaky": verdict.flaky,
        "true_regression": verdict.true_regression,
        "resampled": verdict.resampled,
        "samples": len(verdict.attempts),
        "annotation": verdict.annotation,
        "attempts": [
            {"ok": attempt.ok, "detail": attempt.detail}
            for attempt in verdict.attempts
        ],
    }
