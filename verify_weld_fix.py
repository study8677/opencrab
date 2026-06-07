#!/usr/bin/env python3
"""Verify the weld was successful - check all files are syntactically correct."""
import py_compile
import sys
from pathlib import Path

files_to_check = [
    "heartbeat.py",
    "run_incomplete_heartbeat_weld_to_done.py",
]

all_ok = True
for f in files_to_check:
    p = Path(f)
    if p.exists():
        try:
            py_compile.compile(f, doraise=True)
            print(f"✓ {f}")
        except py_compile.PyCompileError as e:
            print(f"✗ {f}: {e}")
            all_ok = False
    else:
        print(f"? {f}: not found")

print()
if all_ok:
    print("All files compile successfully!")
    sys.exit(0)
else:
    print("Some files have syntax errors!")
    sys.exit(1)

# Also try importing heartbeat
print("\nTrying import heartbeat...")
try:
    import heartbeat
    print(f"✓ heartbeat imported, pulse={heartbeat.pulse}")
    print(f"  get_task_status test: {heartbeat.get_task_status('test_incomplete_heartbeat_weld')}")
except Exception as e:
    print(f"✗ heartbeat import failed: {e}")
    sys.exit(1)
