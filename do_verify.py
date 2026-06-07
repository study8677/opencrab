#!/usr/bin/env python3
"""Run verification."""
import subprocess, sys
r = subprocess.run([sys.executable, "verify_weld_fix.py"], capture_output=True, text=True)
print(r.stdout)
if r.stderr: print("STDERR:", r.stderr)
sys.exit(r.returncode)
