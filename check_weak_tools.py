#!/usr/bin/env python3
"""检查弱格查找和 delta 计算工具"""
from pathlib import Path

REPO_ROOT = Path(__file__).parent

for fname in ["find_weakest_cell.py", "fitness_delta.py", "peek_weakest.py"]:
    p = REPO_ROOT / fname
    print(f"\n{'='*60}")
    print(f"📄 {fname}")
    print(f"   存在: {p.exists()}")
    if p.exists():
        lines = p.read_text().splitlines()
        print(f"   行数: {len(lines)}")
        # 显示前40行
        for i, line in enumerate(lines[:40], 1):
            print(f"   {i:3}: {line[:100]}")
