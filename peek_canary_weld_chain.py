#!/usr/bin/env python3
"""Peek: read key modules for canary weld chain"""
import sys

def main():
    files = [
        "analyze_weakest_cell.py",
        "autopsy_canary_75_25pct_rootcause.py",
        "brainonly_canary_patch.py",
        "run_canary_75_autopsy_25pct.py",
        "fitness.json",
    ]
    for f in files:
        try:
            with open(f) as fp:
                content = fp.read()
            print(f"\n{'='*60}")
            print(f"FILE: {f} ({len(content)} bytes)")
            print('='*60)
            # first 80 lines
            lines = content.splitlines()[:80]
            for i, line in enumerate(lines, 1):
                print(f"{i:3}: {line}")
            if len(content.splitlines()) > 80:
                print(f"... ({len(content.splitlines())-80} more lines)")
        except FileNotFoundError:
            print(f"NOT FOUND: {f}")

if __name__ == "__main__":
    main()
