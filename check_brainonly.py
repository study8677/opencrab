#!/usr/bin/env python3
"""检查 brain-only 相关文件和三闸的集成"""
from pathlib import Path
import re

REPO_ROOT = Path(__file__).parent

# 检查 patchcourse_brainonly.py
p = REPO_ROOT / "patchcourse_brainonly.py"
print(f"\n{'='*60}")
print(f"📄 patchcourse_brainonly.py")
if p.exists():
    content = p.read_text()
    print(f"   行数: {len(content.splitlines())}")
    print("   前50行:")
    for i, line in enumerate(content.splitlines()[:50], 1):
        print(f"   {i:3}: {line[:100]}")
else:
    print("   ❌ 不存在")

# 检查 patchfitroom_brainonly_retry.py
p = REPO_ROOT / "patchfitroom_brainonly_retry.py"
print(f"\n{'='*60}")
print(f"📄 patchfitroom_brainonly_retry.py")
if p.exists():
    content = p.read_text()
    print(f"   行数: {len(content.splitlines())}")
    print("   前50行:")
    for i, line in enumerate(content.splitlines()[:50], 1):
        print(f"   {i:3}: {line[:100]}")
else:
    print("   ❌ 不存在")

# 检查 patchfitroom.py 的结构
p = REPO_ROOT / "patchfitroom.py"
print(f"\n{'='*60}")
print(f"📄 patchfitroom.py")
if p.exists():
    content = p.read_text()
    print(f"   行数: {len(content.splitlines())}")
    # 找主要函数
    funcs = re.findall(r'def (\w+)\(', content)
    classes = re.findall(r'class (\w+)', content)
    print(f"   类: {classes}")
    print(f"   函数: {funcs[:15]}")
    print("   前40行:")
    for i, line in enumerate(content.splitlines()[:40], 1):
        print(f"   {i:3}: {line[:100]}")
else:
    print("   ❌ 不存在")
