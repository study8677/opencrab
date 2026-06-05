#!/usr/bin/env python3
"""检查 patchfitroom.py 的当前状态"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent
p = REPO_ROOT / "patchfitroom.py"

if p.exists():
    content = p.read_text()
    print(f"patchfitroom.py - {len(content.splitlines())} 行")
    print("="*60)
    for i, line in enumerate(content.splitlines()[:80], 1):
        print(f"{i:3}: {line[:100]}")
else:
    print("patchfitroom.py 不存在")
