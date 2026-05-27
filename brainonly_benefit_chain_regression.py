"""Minimal regression for the brain-only claw benefit chain.

The goal is deliberately small:
- take the latest five brain-only claws,
- connect patchnote/evidence/autonomy/harvest proof for each claw,
- report the exact missing link as a breakpoint.

This module is pure-Python and has no dependency on the storage shape used by the
rest of the project.  Callers may pass dict records collected from patchnote,
evidence, autonomy, and harvest ledgers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


CHAIN_LINKS: Tuple[str, ...] = ("patchnote", "evidence", "autonomy", "harvest")


@dataclass(frozen=True)
class BenefitChain:
    """A compact proof chain for one brain-only claw."""

    claw_id: str
    timestamp: str
    patchnote: Optional[str]
    evidence: Optional[str]
    autonomy: Optional[str]
    harvest: Optional[str]

    def missing_links(self) -> List[str]:
        missing: List[str] = []
        for name in CHAIN_LINKS:
            if not getattr(self, name):
                missing.append(name)
        return missing

    def is_complete(self) -> bool:
        return not self.missing_links()


def _string(record: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = record.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _number(record: Mapping[str, Any], *keys: str) -> Optional[float]:
    for key in keys:
        value = record.get(key)
        if value is None or value == "":
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _is_brain_only(record: Mapping[str, Any]) -> bool:
    if bool(record.get("brain_only")):
        return True
    mode = _string(record, "mode", "route", "execution_mode", "actor")
    if mode and mode.replace("_", "-").lower() in {"brain-only", "brainonly"}:
        return True
    tags = record.get("tags")
    if isinstance(tags, (list, tuple, set)):
        return any(str(tag).replace("_", "-").lower() == "brain-only" for tag in tags)
    if isinstance(tags, str):
        normalized = tags.replace("_", "-").lower()
        return "brain-only" in normalized or "brainonly" in normalized
    return False


def _claw_id(record: Mapping[str, Any]) -> str:
    return (
        _string(record, "claw_id", "patch_id", "change_id", "id", "slug")
        or "unknown-claw"
    )


def _timestamp(record: Mapping[str, Any]) -> str:
    return _string(record, "timestamp", "time", "created_at", "date") or ""


def _order_key(record: Mapping[str, Any]) -> Tuple[str, str]:
    sequence = _string(record, "seq", "sequence", "index")
    return (_timestamp(record), sequence or "")


def recent_brain_only(records: Iterable[Mapping[str, Any]], limit: int = 5) -> List[Mapping[str, Any]]:
    """Return the latest brain-only records in chronological-descending order."""

    selected = [record for record in records if _is_brain_only(record)]
    selected.sort(key=_order_key, reverse=True)
    return selected[:limit]


def build_benefit_chain(record: Mapping[str, Any]) -> BenefitChain:
    """Normalize one record into the four-link benefit proof chain."""

    patchnote = _string(record, "patchnote", "patch_note", "note", "summary")

    evidence = _string(record, "evidence", "evidence_id", "proof", "regression")
    if not evidence and bool(record.get("tests_passed")):
        evidence = "tests_passed"

    autonomy = _string(record, "autonomy", "autonomy_note", "autonomy_delta")
    if not autonomy:
        delta = _number(record, "autonomy_gain", "autonomy_score_delta")
        if delta is not None and delta > 0:
            autonomy = f"autonomy_gain={delta:g}"

    harvest = _string(record, "harvest", "harvest_note", "benefit", "impact")
    if not harvest:
        gain = _number(record, "harvest_gain", "value_gain", "benefit_score")
        if gain is not None and gain > 0:
            harvest = f"harvest_gain={gain:g}"

    return BenefitChain(
        claw_id=_claw_id(record),
        timestamp=_timestamp(record),
        patchnote=patchnote,
        evidence=evidence,
        autonomy=autonomy,
        harvest=harvest,
    )


def latest_five_benefit_chains(records: Iterable[Mapping[str, Any]]) -> List[BenefitChain]:
    """Build chains for the latest five brain-only claws."""

    return [build_benefit_chain(record) for record in recent_brain_only(records, limit=5)]


def find_breakpoints(chains: Sequence[BenefitChain]) -> Dict[str, List[str]]:
    """Return claw_id -> missing chain links for incomplete chains."""

    broken: Dict[str, List[str]] = {}
    for chain in chains:
        missing = chain.missing_links()
        if missing:
            broken[chain.claw_id] = missing
    return broken


def assert_latest_five_have_benefit_chain(records: Iterable[Mapping[str, Any]]) -> List[BenefitChain]:
    """Regression helper: fail with the exact missing link if the chain breaks."""

    chains = latest_five_benefit_chains(records)
    breakpoints = find_breakpoints(chains)
    if breakpoints:
        details = "; ".join(
            f"{claw_id}: missing {', '.join(missing)}"
            for claw_id, missing in sorted(breakpoints.items())
        )
        raise AssertionError(f"brain-only benefit chain breakpoint: {details}")
    return chains


def _complete_fixture() -> List[Dict[str, Any]]:
    return [
        {
            "id": f"brain-claw-{idx}",
            "timestamp": f"2026-05-2{idx}T00:00:00Z",
            "mode": "brain-only",
            "patchnote": "small self-change recorded",
            "evidence": "py_compile/import regression",
            "autonomy_gain": 0.1,
            "harvest_gain": 1,
        }
        for idx in range(1, 7)
    ]


def test_latest_five_complete_chain_regression() -> None:
    chains = assert_latest_five_have_benefit_chain(_complete_fixture())
    assert len(chains) == 5
    assert all(chain.is_complete() for chain in chains)


def test_breakpoint_names_missing_link_regression() -> None:
    records = _complete_fixture()
    records[-1] = dict(records[-1])
    records[-1].pop("harvest_gain")
    records[-1].pop("harvest", None)

    chains = latest_five_benefit_chains(records)
    breakpoints = find_breakpoints(chains)

    assert breakpoints == {"brain-claw-6": ["harvest"]}


if __name__ == "__main__":
    test_latest_five_complete_chain_regression()
    test_breakpoint_names_missing_link_regression()
    print("brain-only benefit chain regression ok")
