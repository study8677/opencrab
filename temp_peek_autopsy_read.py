#!/usr/bin/env python3
"""Quick peek at autopsy root cause findings"""
import os, glob

autopsy_files = [
    "autopsy_weld_rootcause.py",
    "autopsy_real_weld.py", 
    "autopsy_do_canary_75_final.py",
]

for f in autopsy_files:
    if os.path.exists(f):
        print(f"\n{'='*60}")
        print(f"FILE: {f}")
        print('='*60)
        with open(f) as fh:
            content = fh.read()
            print(content[:3000])
            if len(content) > 3000:
                print(f"\n... [{len(content)-3000} more chars]")
                
# Also check fitness.json to see current scores
if os.path.exists("fitness.json"):
    print("\n" + "="*60)
    print("FILE: fitness.json (current state)")
    print("="*60)
    with open("fitness.json") as fh:
        print(fh.read()[:2000])
