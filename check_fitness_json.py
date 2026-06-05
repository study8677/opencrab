#!/usr/bin/env python3
"""检查 fitness.json 和 state"""
import json
from pathlib import Path
from datetime import datetime

REPO_ROOT = Path(__file__).parent

# 检查 fitness.json
fp = REPO_ROOT / "fitness.json"
print("="*50)
print(f"📄 fitness.json: {fp}")
print(f"   存在: {fp.exists()}")
if fp.exists():
    with open(fp) as f:
        data = json.load(f)
    print(f"   内容: {json.dumps(data, indent=2)[:500]}")

# 检查 state/projects/fitness-baseline.md
mdp = REPO_ROOT / "state" / "projects" / "fitness-baseline.md"
print(f"\n📄 fitness-baseline.md: {mdp}")
print(f"   存在: {mdp.exists()}")
if mdp.exists():
    content = mdp.read_text()
    print(f"   前30行:")
    for i, line in enumerate(content.splitlines()[:30], 1):
        print(f"   {i:3}: {line[:100]}")
