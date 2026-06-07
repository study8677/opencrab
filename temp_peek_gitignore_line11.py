#!/usr/bin/env python3
"""Quick peek at .gitignore line 11."""
import subprocess

print("=== Line 11 ===")
try:
    with open(".gitignore") as f:
        lines = f.readlines()
    if len(lines) >= 11:
        print(f"Line 11: {repr(lines[10].rstrip())}")
except FileNotFoundError:
    print(".gitignore not found")

print("\n=== git check-ignore -v state/projects/项目账.md ===")
result = subprocess.run(["git", "check-ignore", "-v", "state/projects/项目账.md"], capture_output=True, text=True)
print(f"stdout: {result.stdout.strip()}")
print(f"returncode: {result.returncode}")

print("\n=== git ls-files state/ ===")
result = subprocess.run(["git", "ls-files", "state/"], capture_output=True, text=True)
print(f"stdout: {result.stdout.strip()}")
print(f"returncode: {result.returncode}")
