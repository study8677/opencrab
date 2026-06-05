#!/usr/bin/env python3
"""临时检查工具 - 查看关键文件状态"""
import json
import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def check_file(path, name):
    p = REPO_ROOT / path
    exists = p.exists()
    print(f"\n{'='*50}")
    print(f"📄 {name}: {path}")
    print(f"   存在: {exists}")
    if exists:
        print(f"   大小: {p.stat().st_size} bytes")
        # 尝试读取前20行
        try:
            with open(p) as f:
                lines = f.readlines()[:20]
            for i, line in enumerate(lines, 1):
                print(f"   {i:3}: {line.rstrip()[:80]}")
        except:
            print("   (无法读取)")
    return exists

# 检查关键文件
check_file("crab.py", "crab.py (主)")
check_file("readpack.py", "readpack.py (第一闸)")
check_file("intentpatch.py", "intentpatch.py (第二闸)")
check_file("patchfitroom.py", "patchfitroom.py (第三闸)")
check_file("fitness.json", "fitness.json (真分存储)")

# 检查 evidence 目录
evidence_dir = REPO_ROOT / "evidence" / "baseline"
print(f"\n{'='*50}")
print(f"📁 evidence/baseline/: {evidence_dir}")
print(f"   存在: {evidence_dir.exists()}")
if evidence_dir.exists():
    for f in sorted(evidence_dir.iterdir())[-5:]:
        print(f"   - {f.name}")

# 检查 state 目录
state_dir = REPO_ROOT / "state" / "projects"
print(f"\n{'='*50}")
print(f"📁 state/projects/: {state_dir}")
print(f"   存在: {state_dir.exists()}")
if state_dir.exists():
    for f in sorted(state_dir.iterdir())[-5:]:
        print(f"   - {f.name}")

print("\n✅ 检查完成")
