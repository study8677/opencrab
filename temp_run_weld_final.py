#!/usr/bin/env python3
"""Run the weld to completion."""
import subprocess
import sys
from pathlib import Path

# First check current state
print("Checking current state before weld...")
result = subprocess.run([sys.executable, "temp_peek_heartbeat_weld.py"], capture_output=True, text=True)
print(result.stdout)

print("\n" + "="*60)
print("NOW RUNNING THE WELD")
print("="*60 + "\n")

# Run the weld
result = subprocess.run([sys.executable, "run_incomplete_heartbeat_weld_to_done.py"], capture_output=True, text=True)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)

print("\n" + "="*60)
print("CHECKING FINAL STATE")
print("="*60 + "\n")

# Check final state
result = subprocess.run([sys.executable, "check_fitness_json.py"], capture_output=True, text=True)
print(result.stdout)
