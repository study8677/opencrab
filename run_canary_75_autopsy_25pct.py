"""
Quick runner: run canary_75 first (if needed), then run the 25pct rootcause autopsy.
"""
import subprocess
import sys

print("Step 1: Checking if canary_75 results already exist...")
import json
from pathlib import Path

# Check for existing results
existing = list(Path(".").glob("*canary*75*.jsonl")) + list(Path(".").glob("*canary*75*.json"))
existing += list(Path("results").glob("*canary*75*")) if Path("results").exists() else []
existing += list(Path("logs").glob("*canary*75*")) if Path("logs").exists() else []

if existing:
    print(f"Found existing files: {[str(p) for p in existing]}")
    print("Skipping canary_75 execution, using existing data.\n")
else:
    print("No existing results found. Need to run canary_75 first.")
    print("Please run one of these commands first:")
    print("  python run_canary_75_final.py")
    print("  python execute_canary_75.py")
    print("\nThen re-run: python run_canary_75_autopsy_25pct.py")

print("Step 2: Running 25% failure rootcause autopsy...")

import subprocess
result = subprocess.run(
    [sys.executable, "autopsy_canary_75_25pct_rootcause.py"],
    capture_output=True,
    text=True,
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print("\nDone.")
