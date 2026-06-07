#!/usr/bin/env python3
"""Quick peek at weld chain interfaces"""
import os, sys

files = [
    "analyze_weakest_cell.py",
    "autopsy_canary_75_25pct_rootcause.py",
    "brainonly_canary_patch.py",
    "run_canary_75_autopsy_25pct.py",
]

for f in files:
    path = f
    if not os.path.exists(path):
        print(f"SKIP: {f} (not found)")
        continue
    with open(path) as fp:
        lines = fp.readlines()
    print(f"\n{'='*60}")
    print(f"FILE: {f} ({len(lines)} lines)")
    print('='*60)
    for i, line in enumerate(lines[:100], 1):
        print(f"{i:3}: {line}", end='')
    if len(lines) > 100:
        print(f"\n... ({len(lines)-100} more)")
