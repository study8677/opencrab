"""Evidence failure circuit breaker.

This module keeps capability claims honest when supporting evidence no longer
validates.  A failed validation event immediately:

1. lowers trust for the affected capability,
2. freezes the capability claim until repair,
3. creates a repair ticket describing what must be revalidated.

The implementation is intentionally dependency-light so it can be used from
validators, release gates, audits, or tests without pulling in the rest of the
runtime.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional


DEFAULT_TRUST_FLOOR = 0.0
DEFAULT_FAILURE_PENALTY = 0.35


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clamp_trust(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


@dataclass
class CapabilityClaim:
    """A claim about what the system can do."""

    capability: str
    trust: float = 1.0
    frozen: bool = False
    evidence_ids: List[str] = field(default_factory=list)
    freeze_reason: Optional[str] = None
    updated_at: str = field(default_factory=_utc_now)

    def lower_trust(self, penalty: float = DEFAULT_FAILURE_PENALTY) -> None:
        self.trust = _clamp_trust(self.trust - penalty)
        self.updated_at = _utc_now()

    def freeze(self, reason: str) -> None:
        self.frozen = True
        self.freeze_reason = reason
        self.updated_at = _utc_now()

    def as_dict(self) -> Dict[str, Any]:
        return {
            "capability": self.capability,
            "trust": self.trust,
            "frozen": self.frozen,
            "evidence_ids": list(self.evidence_ids),
            "freeze_reason": self.freeze_reason,
            "updated_at": self.updated_at,
        }


@dataclass
class RepairTicket:
    """A concrete repair request created by the circuit breaker."""

    ticket_id: str
    capability: str
    failed_evidence_id: str
    reason: str
    status: str = "open"
    created_at: str = field(default_factory=_utc_now)
    required_actions: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "ticket_id": self.ticket_id,
            "capability": self.capability,
            "failed_evidence_id": self.failed_evidence_id,
            "reason": self.reason,
            "status": self.status,
            "created_at": self.created_at,
            "required_actions": list(self.required_actions),
        }


class EvidenceCircuitBreaker:
    """Apply evidence-failure consequences to capability claims."""

    def __init__(
        self,
        claims: Optional[Mapping[str, CapabilityClaim]] = None,
        *,
        failure_penalty: float = DEFAULT_FAILURE_PENALTY,
        trust_floor: float = DEFAULT_TRUST_FLOOR,
    ) -> None:
        self.claims: Dict[str, CapabilityClaim] = dict(claims or {})
        self.failure_penalty = _clamp_trust(failure_penalty)
        self.trust_floor = _clamp_trust(trust_floor)
        self.tickets: List[RepairTicket] = []

    def ensure_claim(
        self,
        capability: str,
        *,
        trust: float = 1.0,
        evidence_ids: Optional[Iterable[str]] = None,
    ) -> CapabilityClaim:
        claim = self.claims.get(capability)
        if claim is None:
            claim = CapabilityClaim(
                capability=capability,
                trust=_clamp_trust(trust),
                evidence_ids=list(evidence_ids or ()),
            )
            self.claims[capability] = claim
        return claim

    def record_validation_failure(
        self,
        *,
        capability: str,
        evidence_id: str,
        reason: str,
        required_actions: Optional[Iterable[str]] = None,
    ) -> RepairTicket:
        """Trip the breaker for one failed evidence validation."""

        claim = self.ensure_claim(capability, evidence_ids=[evidence_id])
        if evidence_id not in claim.evidence_ids:
            claim.evidence_ids.append(evidence_id)

        claim.lower_trust(self.failure_penalty)
        if claim.trust < self.trust_floor:
            claim.trust = self.trust_floor
        claim.freeze("evidence validation failed: " + reason)

        ticket = RepairTicket(
            ticket_id=self._ticket_id(capability, evidence_id),
            capability=capability,
            failed_evidence_id=evidence_id,
            reason=reason,
            required_actions=list(required_actions or self.default_required_actions()),
        )
        self.tickets.append(ticket)
        return ticket

    def default_required_actions(self) -> List[str]:
        return [
            "inspect the failed evidence and validator output",
            "replace or refresh stale evidence",
            "rerun validation before unfreezing the capability claim",
        ]

    def claim_state(self, capability: str) -> Dict[str, Any]:
        return self.ensure_claim(capability).as_dict()

    def export_state(self) -> Dict[str, Any]:
        return {
            "claims": {name: claim.as_dict() for name, claim in sorted(self.claims.items())},
            "repair_tickets": [ticket.as_dict() for ticket in self.tickets],
        }

    def write_jsonl(self, path: str | Path) -> None:
        """Append current repair tickets as JSONL for audit or triage."""

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            for ticket in self.tickets:
                handle.write(json.dumps(ticket.as_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")

    def _ticket_id(self, capability: str, evidence_id: str) -> str:
        safe_capability = "".join(ch if ch.isalnum() else "-" for ch in capability).strip("-")
        safe_evidence = "".join(ch if ch.isalnum() else "-" for ch in evidence_id).strip("-")
        ordinal = len(self.tickets) + 1
        return f"repair-{safe_capability or 'capability'}-{safe_evidence or 'evidence'}-{ordinal}"


def trip_on_failed_validation(
    claims: MutableMapping[str, CapabilityClaim],
    *,
    capability: str,
    evidence_id: str,
    reason: str,
    failure_penalty: float = DEFAULT_FAILURE_PENALTY,
) -> RepairTicket:
    """Convenience API for callers that already maintain a claim mapping."""

    breaker = EvidenceCircuitBreaker(claims, failure_penalty=failure_penalty)
    ticket = breaker.record_validation_failure(
        capability=capability,
        evidence_id=evidence_id,
        reason=reason,
    )
    claims.clear()
    claims.update(breaker.claims)
    return ticket
