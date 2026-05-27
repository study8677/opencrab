"""Regression checks for the formerly-unknown organ verifier."""

from __future__ import annotations

import organ_verification


def test_three_former_unknown_organs_are_declared() -> None:
    assert set(organ_verification.CLAIMS) == {"astlocator", "budget", "trustscore"}
    for claim in organ_verification.CLAIMS.values():
        assert claim.former_mark == "?"
        assert claim.capability
        assert claim.evidence_goal


def test_verifier_collects_minimal_evidence_schema() -> None:
    evidence = organ_verification.verify_all()
    assert len(evidence) == 3
    for item in evidence:
        assert item.module in organ_verification.CLAIMS
        assert isinstance(item.import_ok, bool)
        assert isinstance(item.public_symbols, list)
        assert item.capability == organ_verification.CLAIMS[item.module].capability
        assert item.verdict in {"verified", "imported-no-public-surface", "blocked"}


def test_cli_rejects_unknown_organs() -> None:
    assert organ_verification.main(["not_an_organ"]) == 2
