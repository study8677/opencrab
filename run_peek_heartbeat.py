#!/usr/bin/env python3
"""Run all the peek/inspect scripts to diagnose the situation."""
import subprocess
import sys
from pathlib import Path

scripts = [
    "peek_heartbeat_weld_status.py",
    "crab_heartbeat_inspect.py",
    "check_fitness_json.py",
]

def run(script):
    print(f"\n{'='*60}")
    print(f"Running: {script}")
    print('='*60)
    p = Path(script)
    if p.exists():
        result = subprocess.run([sys.executable, script], capture_output=True, text=True)
        print(result.stdout)
        if result.stderr:
            print("STDERR:", result.stderr)
    else:
        print(f"  File not found: {script}")

for s in scripts:
    run(s)
