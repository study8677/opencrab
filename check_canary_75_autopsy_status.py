"""
Quick status check: what's the current canary_75 failure distribution?
"""
import json
import subprocess
import sys

print("=== Canary 75% Failure Distribution Quick Check ===\n")

# Try running the autopsy script
result = subprocess.run(
    [sys.executable, "autopsy_canary_75_25pct_rootcause.py"],
    capture_output=True,
    text=True,
)
print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)

# Also check for any recent canary_75 logs
from pathlib import Path
print("\n=== Files mentioning canary_75 ===")
for p in list(Path(".").glob("*canary*75*"))[:10]:
    print(f"  {p}")

# Check results directory
if Path("results").exists():
    results_files = list(Path("results").glob("*canary*"))
    if results_files:
        print(f"\n=== In results/ ===")
        for p in results_files[:10]:
            print(f"  {p}")
