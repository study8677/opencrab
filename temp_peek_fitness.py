import json
from pathlib import Path

# 看 fitness.json 当前状态
fp = Path("fitness.json")
if fp.exists():
    with open(fp) as f:
        data = json.load(f)
    print("=== fitness.json ===")
    print(f"keys: {list(data.keys())}")
    print(f"total_delta: {data.get('total_delta', 'N/A')}")
    print(f"weld_count: {data.get('weld_count', 'N/A')}")
    print(f"score: {data.get('score', 'N/A')}")
    print(f"runs 条目数: {len(data.get('runs', []))}")
    if data.get('runs'):
        print(f"\n最近 3 条 runs:")
        for r in data['runs'][-3:]:
            print(f"  {r}")
else:
    print("fitness.json 不存在")

# 看 crab 当前的 cells 状态
print("\n=== crab.py cells 状态 ===")
crab = Path("crab.py")
if crab.exists():
    src = crab.read_text()
    # 找 cells 数据结构
    if "self.cells" in src or "cells = {" in src or "cells =" in src:
        # 找初始化
        idx = src.find("self.cells")
        if idx < 0:
            idx = src.find("cells =")
        print(src[max(0, idx-100):idx+500])
