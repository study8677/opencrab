#!/usr/bin/env python3
"""Run the heartbeat weld script and check results."""
import subprocess
import sys

result = subprocess.run([sys.executable, "run_incomplete_heartbeat_weld_to_done.py"], 
                       capture_output=True, text=True)
print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print(f"\nReturn code: {result.returncode}")

# Check the state after
import json
from pathlib import Path

tasks_file = Path("state/heartbeat_tasks.json")
if tasks_file.exists():
    tasks = json.loads(tasks_file.read_text())
    for t in tasks:
        if t.get("name") == "test_incomplete_heartbeat_weld":
            print(f"\nFinal task state: {json.dumps(t, indent=2)}")
            break
else:
    print("No tasks file found")

fitness_file = Path("state/fitness.json")
if fitness_file.exists():
    fitness = json.loads(fitness_file.read_text())
    print(f"Fitness: {fitness.get('test_incomplete_heartbeat_weld')}")
