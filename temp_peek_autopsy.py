#!/usr/bin/env python3
"""Quick peek at autopsy results for canary 75%"""
import os, glob

# Find autopsy files
autopsy_files = sorted(glob.glob("*autopsy*.py")) + sorted(glob.glob("*canary_75*.py"))
print("=== AUTOPSY/CANARY FILES ===")
for f in autopsy_files[:10]:
    print(f)

# Read autopsy_weld_rootcause.py for root cause findings
print("\n=== AUTOPSY_WELD_ROOTCAUSE ===")
if os.path.exists("autopsy_weld_rootcause.py"):
    with open("autopsy_weld_rootcause.py") as f:
        content = f.read()
        # Find key sections about 25% dead causes
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if any(kw in line.lower() for kw in ['dead', '25%', 'cause', 'root']):
                start = max(0, i-2)
                end = min(len(lines), i+3)
                print(f"Line {i}: {lines[i]}")
                for j in range(start, end):
                    print(f"  {j}: {lines[j]}")
                print("---")
                break

# Read do_canary_80_final.py for what 80% needs
print("\n=== DO_CANARY_80_FINAL ===")
if os.path.exists("do_canary_80_final.py"):
    with open("do_canary_80_final.py") as f:
        print(f.read()[:2000])

# Check fitness.json structure
print("\n=== FITNESS.JSON CHECK ===")
if os.path.exists("fitness.json"):
    import json
    with open("fitness.json") as f:
        data = json.load(f)
    if isinstance(data, dict):
        print(f"Keys: {list(data.keys())[:10]}")
        for k, v in list(data.items())[:5]:
            print(f"  {k}: {str(v)[:100]}")
    else:
        print(f"Type: {type(data)}, len={len(data)}")
else:
    print("fitness.json not found, checking generate_fitness_json.py")
    if os.path.exists("generate_fitness_json.py"):
        with open("generate_fitness_json.py") as f:
            print(f.read()[:1500])

# Check patchfitroom structure
print("\n=== PATCHFITROOM GATES ===")
if os.path.exists("patchfitroom.py"):
    with open("patchfitroom.py") as f:
        content = f.read()
        # Find gate functions
        lines = content.split('\n')
        for i, line in enumerate(lines):
            if 'def gate' in line.lower() or 'class' in line.lower():
                print(f"Line {i}: {line}")
