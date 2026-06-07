#!/usr/bin/env python3
"""peek_fitness_baseline_quick_context.py — 快速瞄基线状态"""

import json
from pathlib import Path

def main():
    fp = Path("fitness.json")
    if not fp.exists():
        print("[peek] fitness.json 不存在")
        return

    data = json.loads(fp.read_text())
    total = len(data)
    passed = sum(1 for v in data.values() if (v.get("score") if isinstance(v, dict) else float(v)) >= 1.0)
    pct = passed / total * 100 if total else 0

    print(f"[peek] 总用例: {total} | 通过: {passed} | 覆盖率: {pct:.1f}%")

    # 最低10条
    scores = {k: (v.get("score") if isinstance(v, dict) else float(v)) for k, v in data.items()}
    worst = sorted(scores.items(), key=lambda x: x[1])[:10]
    print(f"[peek] 最弱10条:")
    for k, v in worst:
        icon = "✅" if v >= 1.0 else "❌"
        print(f"  {icon} {k}: {v:.3f}")

if __name__ == "__main__":
    main()
