#!/usr/bin/env python3
"""Run the peek scripts"""
import subprocess, sys

scripts = ["temp_peek_autopsy_read.py", "temp_peek_canary_75_real.py"]

for s in scripts:
    result = subprocess.run([sys.executable, s], capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
