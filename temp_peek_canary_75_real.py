#!/usr/bin/env python3
"""Peek at canary 75 real weld defect details"""
import os

files_to_check = [
    "canary_75_real_weld.py",
    "canary_75_real_landing.py", 
    "create_canary_75_minimal_patch.py",
    "check_canary_75_real_weld.py",
]

for f in files_to_check:
    if os.path.exists(f):
        print(f"\n{'='*60}")
        print(f"FILE: {f}")
        print('='*60)
        with open(f) as fh:
            content = fh.read()
            print(content[:2500])
            if len(content) > 2500:
                print(f"\n... [{len(content)-2500} more chars]")
