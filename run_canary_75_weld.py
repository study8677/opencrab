#!/usr/bin/env python3
"""运行 canary_75_real_weld 并验证结果写入 fitness.json"""
import subprocess
import sys
import json
from pathlib import Path

print("=" * 60)
print("运行 canary_75_real_weld.py")
print("=" * 60)

result = subprocess.run(
    [sys.executable, "canary_75_real_weld.py"],
    capture_output=True,
    text=True,
    timeout=60
)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr)
print(f"返回码: {result.returncode}")

# 检查 fitness.json
print("\n" + "=" * 60)
print("检查 fitness.json")
print("=" * 60)

fp = Path("fitness.json")
if fp.exists():
    with open(fp) as f:
        data = json.load(f)
    print(f"keys: {list(data.keys())}")
    print(f"total_delta: {data.get('total_delta', 'N/A')}")
    print(f"weld_count: {data.get('weld_count', 'N/A')}")
    print(f"runs 条目数: {len(data.get('runs', []))}")
    if data.get('runs'):
        print("\n最近 3 条 runs:")
        for r in data['runs'][-3:]:
            print(f"  {r}")
else:
    print("fitness.json 不存在")
