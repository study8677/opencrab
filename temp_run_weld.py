#!/usr/bin/env python3
import subprocess, sys
r = subprocess.run([sys.executable, "canary_75_weld.py"], capture_output=True, text=True, timeout=60)
print("STDOUT:", r.stdout[:3000])
print("STDERR:", r.stderr[:1000])
print("RC:", r.returncode)
