#!/usr/bin/env python3
"""Inspect showcase_refresher.py and docs/index.html state."""
import os

# Check showcase_refresher.py
print("=== showcase_refresher.py ===")
if os.path.exists('showcase_refresher.py'):
    with open('showcase_refresher.py') as f:
        print(f.read())
else:
    print("NOT FOUND")

print("\n=== docs/index.html placeholder status ===")
if os.path.exists('docs/index.html'):
    with open('docs/index.html') as f:
        html = f.read()
    for ph in ['<!-- MODULE_COUNT -->', '<!-- COMMIT_COUNT -->', '<!-- SKILL_COUNT -->']:
        print(f"  {ph}: {'FOUND' if ph in html else 'MISSING'}")
else:
    print("NOT FOUND")
