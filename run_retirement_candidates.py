#!/usr/bin/env python3
"""Run retirement drill to find zero-ref candidates."""

import subprocess
import sys

# Run retirement_drill to find candidates
result = subprocess.run(
    [sys.executable, "retirement_drill.py"],
    capture_output=True,
    text=True
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
print("Return code:", result.returncode)
