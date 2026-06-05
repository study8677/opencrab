#!/usr/bin/env python3
"""检查 intentpatch.py 的当前状态"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent
p = REPO_ROOT / "intentpatch.py"

if p.exists():
    content = p.read_text()
    print(f"intentpatch.py - {len(content.splitlines())} 行")
    print("="*60)
    for i, line in enumerate(content.splitlines()[:60], 1):
        print(f"{i:3}: {line[:100]}")
else:
    print("intentpatch.py 不存在")
