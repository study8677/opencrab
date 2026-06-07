# Quick peek at canary_brainonly_3x_compare.py
import os

path = "canary_brainonly_3x_compare.py"
if os.path.exists(path):
    with open(path) as f:
        content = f.read()
    print(f"=== {path} ({len(content)} chars) ===")
    print(content[:3000])
else:
    print(f"FILE NOT FOUND: {path}")
