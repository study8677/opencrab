#!/usr/bin/env python3
"""Temp peek - what is test_incomplete_heartbeat_weld status right now?"""
import json
from pathlib import Path

print("=== TEMP PEEK: test_incomplete_heartbeat_weld ===\n")

# 1. Check heartbeat_tasks.json
tasks_file = Path("state/heartbeat_tasks.json")
if tasks_file.exists():
    with open(tasks_file) as f:
        tasks = json.load(f)
    print("heartbeat_tasks.json:")
    for t in tasks:
        name = t.get("name", "") or t.get("task", "")
        if "incomplete" in name.lower():
            print(f"  {json.dumps(t, indent=2)}")
else:
    print("heartbeat_tasks.json: NOT FOUND")

# 2. Check fitness.json
fitness_file = Path("state/fitness.json")
if fitness_file.exists():
    with open(fitness_file) as f:
        fitness = json.load(f)
    print("\nfitness.json entries with 'incomplete' or 'heartbeat':")
    for k, v in fitness.items():
        if "incomplete" in k.lower() or "heartbeat" in k.lower():
            print(f"  {k}: {v}")
    if not any("incomplete" in k.lower() for k in fitness):
        print("  (none found)")
else:
    print("fitness.json: NOT FOUND")

# 3. Check projects_ledger.json
ledger = Path("state/projects_ledger.json")
if ledger.exists():
    with open(ledger) as f:
        projects = json.load(f)
    print("\nprojects_ledger.json entries with 'incomplete' or 'heartbeat':")
    for p in projects:
        name = p.get("name", "")
        if "incomplete" in name.lower():
            print(f"  {json.dumps(p, indent=2)}")
else:
    print("projects_ledger.json: NOT FOUND")

# 4. Check if there's a test file
test_file = Path("test_incomplete_heartbeat_weld.py")
if test_file.exists():
    print(f"\ntest_incomplete_heartbeat_weld.py exists: {test_file.stat().st_size} bytes")
else:
    print("\ntest_incomplete_heartbeat_weld.py: NOT FOUND")
