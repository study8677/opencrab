#!/usr/bin/env python3
import subprocess
import sys

# First, print showcase_refresher.py
print("=" * 60)
print("showcase_refresher.py:")
print("=" * 60)
try:
    with open('showcase_refresher.py', 'r') as f:
        print(f.read())
except FileNotFoundError:
    print("FILE NOT FOUND")

print("\n" + "=" * 60)
print("docs/index.html placeholders check:")
print("=" * 60)
try:
    with open('docs/index.html', 'r') as f:
        content = f.read()
    for ph in ['<!-- MODULE_COUNT -->', '<!-- COMMIT_COUNT -->', '<!-- SKILL_COUNT -->']:
        print(f"  {ph}: {'FOUND' if ph in content else 'MISSING'}")
except FileNotFoundError:
    print("FILE NOT FOUND")
