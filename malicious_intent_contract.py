"""Minimal contract for recognising malicious intent.

This module is intentionally small and dependency-free: other organs can import
it without pulling in policy engines or evaluators.  The contract is conservative:
it only returns a malicious verdict when an intent names a harmful goal and does
not treat defensive/educational wording alone as sufficient.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Sequence


_MALICIOUS_PATTERNS: Sequence[tuple[str, str]] = (
    ("credential_theft", r"\b(steal|harvest|phish|dump|exfiltrate)\b.{0,80}\b(passwords?|credentials?|tokens?|cookies?|api keys?)\b"),
    ("unauthorised_exfiltration", r"\b(exfiltrate|smuggle|leak|copy out)\b.{0,80}\b(data|database|files?|secrets?)\b"),
    ("malware_or_persistence", r"\b(ransomware|keylogger|backdoor|botnet|worm|trojan)\b|\b(persistence|startup)\b.{0,80}\b(stealth|without (?:the )?user|undetected)\b"),
    ("evasion_or_bypass", r"\b(bypass|evade|disable)\b.{0,80}\b(edr|antivirus|audit|logging|detection|rate limit|access control)\b"),
    ("unauthorised_access", r"\b(break into|hack into|gain unauthori[sz]ed access|privilege escalation)\b"),
)

_BENIGN_CONTEXT = re.compile(
    r"\b(defensive|authorized|authorised|own system|lab|toy example|detect|block|report|audit|training|ctf|sandbox)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class MaliciousIntentVerdict:
    """Result required by the malicious-intent contract."""

    is_malicious: bool
    category: str
    evidence: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "is_malicious": self.is_malicious,
            "category": self.category,
            "evidence": list(self.evidence),
        }


def classify_malicious_intent(text: str) -> MaliciousIntentVerdict:
    """Classify whether *text* states a malicious goal.

    Contract:
    - accepts any object convertible to text;
    - never raises for empty input;
    - returns ``is_malicious=True`` only with a non-empty category and evidence;
    - treats clear defensive/authorised context as non-malicious unless an
      explicit harmful goal is still present.
    """

    normalized = str(text or "").strip()
    if not normalized:
        return MaliciousIntentVerdict(False, "empty", ())

    defensive_context = bool(_BENIGN_CONTEXT.search(normalized))
    for category, pattern in _MALICIOUS_PATTERNS:
        match = re.search(pattern, normalized, re.IGNORECASE | re.DOTALL)
        if not match:
            continue
        evidence = (match.group(0).strip(),)
        if defensive_context and category in {"evasion_or_bypass", "unauthorised_access"}:
            return MaliciousIntentVerdict(False, "benign_defensive_context", evidence)
        return MaliciousIntentVerdict(True, category, evidence)

    return MaliciousIntentVerdict(False, "no_malicious_goal", ())


def verify_malicious_intent_contract(samples: Iterable[tuple[str, bool]]) -> dict[str, object]:
    """Run a tiny contract check over labelled samples."""

    checked = 0
    failures: list[dict[str, object]] = []
    for text, expected in samples:
        checked += 1
        verdict = classify_malicious_intent(text)
        if verdict.is_malicious != bool(expected):
            failures.append(
                {
                    "text": text,
                    "expected": bool(expected),
                    "actual": verdict.as_dict(),
                }
            )
    return {
        "ok": not failures,
        "checked": checked,
        "failures": failures,
    }


__all__ = [
    "MaliciousIntentVerdict",
    "classify_malicious_intent",
    "verify_malicious_intent_contract",
]
