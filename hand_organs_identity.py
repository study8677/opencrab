"""Named contracts and lightweight evidence probes for self-hand organs.

This module makes two previously opaque hand organs easier to reason about:

* ``hands_astbridge``: the AST-side bridge used by hand organs when a textual
  patch needs structural awareness.
* ``patchfitroom_brainonly_retry``: the brain-only retry fit room used when a
  patch attempt must be re-evaluated without relying on external execution.

The probes here are intentionally conservative.  They do not execute target
workflows or mutate files; they only import modules and inspect their public
surface.  The result is a small, JSON-serialisable evidence packet that can be
used by drills, audits, or future organ-verification code.
"""

from __future__ import annotations

import importlib
import inspect
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Tuple


@dataclass(frozen=True)
class OrganContract:
    """Human-readable contract for a hand organ.

    ``required_capabilities`` are semantic expectations, not hard attribute
    names.  ``surface_hints`` are public names that count as supporting evidence
    when present in the inspected module.
    """

    organ: str
    real_name: str
    purpose: str
    required_capabilities: Tuple[str, ...]
    surface_hints: Tuple[str, ...] = field(default_factory=tuple)
    evidence_floor: int = 1

    def as_dict(self) -> Dict[str, Any]:
        return {
            "organ": self.organ,
            "real_name": self.real_name,
            "purpose": self.purpose,
            "required_capabilities": list(self.required_capabilities),
            "surface_hints": list(self.surface_hints),
            "evidence_floor": self.evidence_floor,
        }


CONTRACTS: Tuple[OrganContract, ...] = (
    OrganContract(
        organ="hands_astbridge",
        real_name="AST bridge hand",
        purpose=(
            "Bridge textual self-modification work with Python AST structure so "
            "patches can be previewed, located, or rewritten with less blind "
            "string surgery."
        ),
        required_capabilities=(
            "importable as a standalone organ",
            "exposes at least one public callable or documented public value",
            "mentions AST, parse, locate, preview, rewrite, span, or bridge semantics",
        ),
        surface_hints=(
            "ast",
            "parse",
            "locate",
            "locator",
            "preview",
            "rewrite",
            "rewriter",
            "span",
            "bridge",
            "apply",
        ),
        evidence_floor=1,
    ),
    OrganContract(
        organ="patchfitroom_brainonly_retry",
        real_name="brain-only patch retry fit room",
        purpose=(
            "Reconsider a candidate patch after an initial fit-room failure using "
            "brain-only evidence, rejection attribution, and retry discipline "
            "instead of external execution."
        ),
        required_capabilities=(
            "importable as a standalone organ",
            "exposes at least one public callable or documented public value",
            "mentions retry, fit, reject, brain-only, attribution, or patch semantics",
        ),
        surface_hints=(
            "retry",
            "fit",
            "fitroom",
            "brain",
            "brainonly",
            "reject",
            "attribution",
            "patch",
            "review",
            "verdict",
        ),
        evidence_floor=1,
    ),
)


def contracts() -> Dict[str, Dict[str, Any]]:
    """Return the registered organ contracts keyed by module name."""

    return {contract.organ: contract.as_dict() for contract in CONTRACTS}


def _public_names(module: Any) -> List[str]:
    return sorted(name for name in dir(module) if not name.startswith("_"))


def _signature_or_kind(value: Any) -> str:
    if callable(value):
        try:
            return str(inspect.signature(value))
        except (TypeError, ValueError):
            return "callable"
    return type(value).__name__


def _name_matches_hint(name: str, hints: Iterable[str]) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in hints)


def inspect_organ(contract: OrganContract) -> Dict[str, Any]:
    """Inspect one organ without invoking its workflow.

    The returned packet is deliberately plain data so it can be embedded in
    evidence logs.  Import failures are captured as evidence instead of raised.
    """

    packet: Dict[str, Any] = {
        "contract": contract.as_dict(),
        "importable": False,
        "public_surface_count": 0,
        "public_callables": {},
        "hinted_public_names": [],
        "evidence_score": 0,
        "contract_met": False,
        "errors": [],
    }

    try:
        module = importlib.import_module(contract.organ)
    except Exception as exc:  # pragma: no cover - defensive evidence capture
        packet["errors"].append(f"{type(exc).__name__}: {exc}")
        return packet

    public_names = _public_names(module)
    hinted = [name for name in public_names if _name_matches_hint(name, contract.surface_hints)]
    callables = {
        name: _signature_or_kind(getattr(module, name))
        for name in public_names
        if callable(getattr(module, name))
    }

    score = 0
    if public_names:
        score += 1
    if callables:
        score += 1
    if hinted:
        score += 1

    packet.update(
        {
            "importable": True,
            "public_surface_count": len(public_names),
            "public_callables": callables,
            "hinted_public_names": hinted,
            "evidence_score": score,
            "contract_met": score >= contract.evidence_floor,
        }
    )
    return packet


def evidence() -> Dict[str, Dict[str, Any]]:
    """Return evidence packets for all named self-hand organs."""

    return {contract.organ: inspect_organ(contract) for contract in CONTRACTS}


def summary() -> Dict[str, Any]:
    """Return a compact readiness summary for dashboards or audits."""

    packets = evidence()
    met = [name for name, packet in packets.items() if packet["contract_met"]]
    missing = [name for name, packet in packets.items() if not packet["contract_met"]]
    return {
        "organs": sorted(packets),
        "contract_met": sorted(met),
        "contract_missing": sorted(missing),
        "all_met": not missing,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(evidence(), ensure_ascii=False, indent=2, sort_keys=True))
