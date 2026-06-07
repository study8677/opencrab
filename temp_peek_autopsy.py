#!/usr/bin/env python3
"""Peek at autopsy files to find smallest canary real defect."""
import os
from pathlib import Path

autopsy_files = [
    "autopsy_canary_75_25pct_rootcause.py",
    "autopsy_canary_80_3x.py",
    "autopsy_do_canary_75_final.py",
    "autopsy_real_weld.py",
    "autopsy_weld_rootcause.py",
]

for fname in autopsy_files:
    if os.path.exists(fname):
        print(f"\n{'='*60}")
        print(f"FILE: {fname}")
        print('='*60)
        with open(fname) as f:
            content = f.read()
            print(content[:3000])
            if len(content) > 3000:
                print(f"\n... [{len(content)-3000} more chars]")
