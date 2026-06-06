#!/usr/bin/env python3
"""Quick peek at showcase_refresher.py and docs/index.html current state."""
import os

# Read showcase_refresher.py
if os.path.exists('showcase_refresher.py'):
    with open('showcase_refresher.py', 'r') as f:
        print("=== showcase_refresher.py ===")
        print(f.read())
else:
    print("showcase_refresher.py not found")

print("\n=== docs/index.html placeholders ===")
if os.path.exists('docs/index.html'):
    with open('docs/index.html', 'r') as f:
        content = f.read()
    for placeholder in ['<!-- MODULE_COUNT -->', '<!-- COMMIT_COUNT -->', '<!-- SKILL_COUNT -->']:
        if placeholder in content:
            print(f"  Found: {placeholder}")
        else:
            print(f"  Missing: {placeholder}")
else:
    print("docs/index.html not found")
