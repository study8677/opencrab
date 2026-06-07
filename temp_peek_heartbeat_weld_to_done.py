#!/usr/bin/env python3
"""Peek the current state before running the weld."""
import json
from pathlib import Path

STATE_DIR = Path("state")
TASKS_FILE = STATE_DIR / "heartbeat_tasks.json"
FITNESS_FILE = STATE_DIR / "fitness.json"

print("=== BEFORE WELD STATE ===\n")

# Check tasks file
print(f"TASKS_FILE exists: {TASKS_FILE.exists()}")
if TASKS_FILE.exists():
    with open(TASKS_FILE) as f:
        tasks = json.load(f)
    print(f"Total tasks: {len(tasks)}")
    for t in tasks:
        if "heartbeat" in t.get("name", "").lower() or "incomplete" in t.get("name", "").lower():
            print(f"  - {t.get('name')}: status={t.get('status')}")
else:
    print("No TASKS_FILE - will be created")

# Check fitness file
print(f"\nFITNESS_FILE exists: {FITNESS_FILE.exists()}")
if FITNESS_FILE.exists():
    with open(FITNESS_FILE) as f:
        fitness = json.load(f)
    print(f"Total fitness entries: {len(fitness)}")
    for k, v in fitness.items():
        if "heartbeat" in k.lower() or "incomplete" in k.lower():
            print(f"  - {k}: {v}")
else:
    print("No FITNESS_FILE - will be created")

# Check heartbeat module
print("\n--- heartbeat.py ---")
import heartbeat
print(f"heartbeat module loaded from: {heartbeat.__file__}")
print(f"has pulse: {hasattr(heartbeat, 'pulse')}")
print(f"has get_task_status: {hasattr(heartbeat, 'get_task_status')}")
print(f"has get_fitness: {hasattr(heartbeat, 'get_fitness')}")

# Test heartbeat functions
print("\n--- Heartbeat Function Tests ---")
test_task = "test_incomplete_heartbeat_weld"
try:
    status = heartbeat.get_task_status(test_task)
    print(f"get_task_status('{test_task}'): {status}")
except Exception as e:
    print(f"get_task_status error: {e}")

try:
    fit = heartbeat.get_fitness(test_task)
    print(f"get_fitness('{test_task}'): {fit}")
except Exception as e:
    print(f"get_fitness error: {e}")

print("\n=== END PEEK ===")
