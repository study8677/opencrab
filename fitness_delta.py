#!/usr/bin/env python3
"""fitness_delta.py — 比较前后两次 fitness 差值"""

import json, sys, argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", default="fitness.json.bak")
    parser.add_argument("--after", default="fitness.json")
    args = parser.parse_args()

    def load(fp):
        if not Path(fp).exists():
            return {}
        return json.loads(Path(fp).read_text())

    before = load(args.before)
    after = load(args.after)

    total = len(after)
    delta_sum = 0.0
    improved = []
    degraded = []

    for k, v in after.items():
        score_after = v.get("score") if isinstance(v, dict) else float(v)
        score_before = (before.get(k, {}).get("score") if isinstance(before.get(k), dict) else float(before.get(k, 0))) if k in before else 0.0

        delta = score_after - score_before
        delta_sum += delta
        if delta > 0:
            improved.append((k, delta))
        elif delta < 0:
            degraded.append((k, delta))

    pct_before = sum(1 for v in before.values() if (v.get("score") if isinstance(v, dict) else float(v)) >= 1.0) / max(1, len(before)) * 100
    pct_after = sum(1 for v in after.values() if (v.get("score") if isinstance(v, dict) else float(v)) >= 1.0) / max(1, len(after)) * 100

    print(f"[delta] 覆盖率: {pct_before:.1f}% -> {pct_after:.1f}% (Δ{pct_after-pct_before:+.1f}%)")
    print(f"[delta] 分数总增量: {delta_sum:+.3f}")
    print(f"[delta] 改进: {len(improved)} | 退化: {len(degraded)}")
    if improved:
        print(f"[delta] 主要改进:")
        for k, d in sorted(improved, key=lambda x: -x[1])[:5]:
            print(f"  +{d:.3f} {k}")
    if degraded:
        print(f"[delta] 退化:")
        for k, d in degraded[:5]:
            print(f"  {d:.3f} {k}")

if __name__ == "__main__":
    main()
