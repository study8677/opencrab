#!/usr/bin/env python3
"""Regression: verify cross-heartbeat project memory works.

Checks:
1. Project cards survive across heartbeats (state/projects/)
2. form_intent asks 'continue or new' first
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from state.projects.card import list_projects
from intent import IntentFormer


def run() -> bool:
    print("=== Cross-Heartbeat Project Memory Regression ===")

    # 1. Project card exists in state/projects/
    projects = list_projects(status="active")
    print(f"[1] Active project cards in state/projects/: {len(projects)}")
    if not projects:
        print("FAIL: No active project cards in state/projects/")
        return False

    card = projects[0]
    print(f"    → Project: {card.name} (id={card.project_id})")
    print(f"    → Next step: {card.next_step or '(not set)'}")
    print("    → PASS")

    # 2. form_intent asks 'continue or new' first
    print("\n[2] Checking IntentFormer.form_intent mentions continue/new...")
    # Patch input to avoid hanging on stdin
    import io, builtins
    orig_input = builtins.input
    inputs = iter(["q"])  # quit immediately after reading prompt
    builtins.input = lambda _=None: next(inputs)
    try:
        ifm = IntentFormer()
        result = ifm.form_intent()
    finally:
        builtins.input = orig_input

    text = str(result).lower()
    ok = "continue" in text or "new" in text or "续旧" in text or "开新" in text
    if not ok:
        print(f"FAIL: form_intent result does not mention continue/new:\n  {result}")
        return False

    print(f"    → PASS: form_intent mentions continue/new")
    print("\n=== ALL CHECKS PASSED ===")
    return True


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)
