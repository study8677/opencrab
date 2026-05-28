#!/usr/bin/env python3
"""Batch probe results summary - all 10 '?' organs verified functional."""
# This file was the probe runner. Results are now incorporated into lexicon.
# Keeping as artifact of the probing session.
RESULTS = {
    "anti_pattern_card": {"verdict": "functional", "caps": ["failure-pattern-tracking"]},
    "autonomy_meter": {"verdict": "functional", "caps": ["autonomy-measurement", "jsonl-audit"]},
    "hands_astbridge": {"verdict": "functional", "caps": ["ast-patching", "brain-only-bridge"]},
    "malicious_intent_generator": {"verdict": "functional", "caps": ["security-regression"]},
    "malicious_intent_regression": {"verdict": "functional", "caps": ["security-regression"]},
    "patchfitroom_brainonly_retry": {"verdict": "functional", "caps": ["patch-retry-logic"]},
    "showcase": {"verdict": "functional", "caps": ["showcase-display", "auto-refresh"]},
    "showcase_freshness_gate": {"verdict": "functional", "caps": ["freshness-gating"]},
    "showcase_refresh_gate": {"verdict": "functional", "caps": ["auto-refresh"]},
    "test_brainonly_graduation_sample": {"verdict": "functional", "caps": ["unit-testing"]},
}
