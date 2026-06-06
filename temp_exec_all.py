#!/usr/bin/env python3
"""临时执行层：验证 + 试跑 canary_75_weld"""
import subprocess, sys, os

scripts = [
    "temp_verify_canary_75_weld.py",
    "temp_run_weld.py",
]

for s in scripts:
    if not os.path.exists(s):
        print(f"SKIP (not found): {s}")
        continue
    print(f"\n{'='*60}\n=== RUNNING: {s} ===\n{'='*60}")
    r = subprocess.run([sys.executable, s], capture_output=True, text=True, timeout=90)
    print(r.stdout[:4000])
    if r.stderr:
        print("STDERR:", r.stderr[:2000])
    print(f"RC={r.returncode}")
