"""Offline cold-start self-modification rehearsal helpers.

This module is intentionally dependency-free and network-free.  It keeps a
small pure-function fix plus machine-readable evidence that the drill can be
replayed from a clean checkout without external assistance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class ColdStartEvidence:
    """Evidence emitted by the offline cold-start rehearsal."""

    drill: str
    network_required: bool
    external_model_required: bool
    pure_function: str
    cases: Tuple[Tuple[str, str], ...]

    def as_dict(self) -> Dict[str, object]:
        return {
            "drill": self.drill,
            "network_required": self.network_required,
            "external_model_required": self.external_model_required,
            "pure_function": self.pure_function,
            "cases": list(self.cases),
        }


def normalize_coldstart_token(token: object) -> str:
    """Return a stable offline token for cold-start drill labels.

    Pure-function fix: labels copied from terminals often contain surrounding
    whitespace, mixed case, or separators such as spaces/underscores.  The
    previous brittle form of this logic treated those variants as different
    labels.  This normalized form makes the rehearsal reproducible offline.

    Examples:
        >>> normalize_coldstart_token(" Offline Cold_Start ")
        'offline-cold-start'
        >>> normalize_coldstart_token(None)
        ''
    """

    if token is None:
        return ""
    text = str(token).strip().lower()
    pieces = text.replace("_", "-").split()
    return "-".join(piece for piece in pieces if piece)


def build_coldstart_evidence(samples: Iterable[object] = ()) -> ColdStartEvidence:
    """Build replayable evidence for the offline cold-start rehearsal."""

    cases = tuple((str(sample), normalize_coldstart_token(sample)) for sample in samples)
    return ColdStartEvidence(
        drill="offline-coldstart-self-edit",
        network_required=False,
        external_model_required=False,
        pure_function="normalize_coldstart_token",
        cases=cases,
    )


def self_check() -> Dict[str, object]:
    """Run the tiny offline rehearsal and return evidence."""

    samples = (" Offline Cold_Start ", "offline cold-start", None)
    evidence = build_coldstart_evidence(samples)
    expected = ("offline-cold-start", "offline-cold-start", "")
    observed = tuple(result for _, result in evidence.cases)
    return {
        "ok": observed == expected,
        "evidence": evidence.as_dict(),
        "expected": expected,
        "observed": observed,
    }


__all__ = [
    "ColdStartEvidence",
    "build_coldstart_evidence",
    "normalize_coldstart_token",
    "self_check",
]
