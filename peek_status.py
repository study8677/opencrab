#!/usr/bin/env python3
"""快速瞄一眼关键状态"""
import json, os, subprocess

# 1. fitness.json 当前内容
print("=== fitness.json ===")
fit_path = "fitness.json"
if os.path.exists(fit_path):
    with open(fit_path) as f:
        d = json.load(f)
    print(json.dumps(d, indent=2))
else:
    print("NOT FOUND")

# 2. 最弱格在哪
print("\n=== 最弱格 ===")
result = subprocess.run(["python", "find_weakest_cell.py"], capture_output=True, text=True)
print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
print(result.stderr[-500:] if result.stderr else "")

# 3. reproduce_canary_3x.py 内容
print("\n=== reproduce_canary_3x.py ===")
with open("reproduce_canary_3x.py") as f:
    print(f.read()[:3000])

# 4. 最近的 git 提交
print("\n=== 最近 git 提交 ===")
result = subprocess.run(["git", "log", "--oneline", "-5"], capture_output=True, text=True)
print(result.stdout)
