#!/usr/bin/env python3
"""Peek at .gitignore line 11 to understand what needs to change."""
from pathlib import Path

gitignore = Path(".gitignore")
if gitignore.exists():
    lines = gitignore.read_text().splitlines()
    for i, line in enumerate(lines, 1):
        print(f"Line {i}: {repr(line)}")
    print(f"\nTotal lines: {len(lines)}")
    if len(lines) >= 11:
        print(f"\nLine 11 is: {repr(lines[10])}")
else:
    print(".gitignore not found")
