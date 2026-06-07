#!/usr/bin/env python3
"""临时脚本：读取 crab.py 中 apply_patch 相关代码"""
from pathlib import Path

p = Path("crab.py")
if p.exists():
    content = p.read_text()
    # 找 apply_patch 相关
    idx = 0
    count = 0
    while True:
        idx = content.find("apply_patch", idx)
        if idx < 0:
            break
        start = max(0, idx - 200)
        end = min(len(content), idx + 500)
        print(f"--- 位置 {idx} ---")
        print(content[start:end])
        print()
        idx += 1
        count += 1
        if count > 3:
            break

    # 找 snapshot 相关
    idx = 0
    count = 0
    while True:
        idx = content.find("snapshot", idx)
        if idx < 0:
            break
        start = max(0, idx - 100)
        end = min(len(content), idx + 300)
        print(f"--- snapshot 位置 {idx} ---")
        print(content[start:end])
        print()
        idx += 1
        count += 1
        if count > 3:
            break
else:
    print("❌ crab.py 不存在")
