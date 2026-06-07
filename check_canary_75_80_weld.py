#!/usr/bin/env python3
"""
核验 canary 75→80 第3拍是否真焊上
1. 读 fitness.json 看 canary 分数是否真高于 75% 基线
2. 查 git log 是否有 3x 复现 commit
3. 看 diff 是否只动 canary 相关代码
"""
import json
import subprocess
import sys
from pathlib import Path

def load_fitness_json():
    p = Path("fitness.json")
    if p.exists():
        return json.loads(p.read_text())
    return {}

def get_git_log(limit=15):
    result = subprocess.run(
        ["git", "log", "--oneline", f"-{limit}"],
        capture_output=True, text=True
    )
    return result.stdout.strip().split("\n")

def get_canary_score(data):
    """从 fitness.json 提取 canary 相关分数"""
    # 尝试各种可能的 key
    for key in ["canary", "canary_75", "canary_80", "canary_percent", "fitness_canary"]:
        if key in data:
            return data[key], key
    # 模糊匹配
    for k, v in data.items():
        if "canary" in k.lower():
            return v, k
    return None, None

def check_git_diff_for_canary():
    """查 git diff 是否只动了 canary 相关代码"""
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD~3..HEAD"],
        capture_output=True, text=True
    )
    files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
    return files

def main():
    print("=" * 60)
    print("CANARY 75→80 焊核验")
    print("=" * 60)

    # 1. 核 fitness.json
    print("\n[1] 核 fitness.json")
    data = load_fitness_json()
    if not data:
        print("  ❌ fitness.json 不存在或为空")
        fitness_score = None
    else:
        fitness_score, key = get_canary_score(data)
        print(f"  canary 相关字段: {key} = {fitness_score}")
        print(f"  全部 keys: {sorted(data.keys())[:10]}...")

    # 2. 核 git log
    print("\n[2] 核 git log (最近15条)")
    log = get_git_log(15)
    for line in log[:10]:
        print(f"  {line}")

    # 3. 查最近 3 个 commit 是否 canary 相关
    print("\n[3] 查最近 commit diff 文件")
    diff_files = check_git_diff_for_canary()
    print(f"  涉及文件: {diff_files}")

    canary_related = [f for f in diff_files if "canary" in f.lower() or f in ["fitness.json", "baseline_scores.json"]]
    print(f"  canary相关文件: {canary_related}")

    # 4. 决策
    print("\n" + "=" * 60)
    print("核验结论")
    print("=" * 60)

    # 判断1: canary 分数 ≥ 75%?
    try:
        score_ok = fitness_score is not None and float(fitness_score) >= 75.0
    except (TypeError, ValueError):
        score_ok = False

    # 判断2: 有 canary 相关的 commit?
    has_canary_commit = any("canary" in line.lower() for line in log[:5])

    # 判断3: diff 只动 canary?
    diff_clean = len(canary_related) > 0 and all(
        "canary" in f.lower() or f in ["fitness.json", "baseline_scores.json"]
        for f in diff_files
    )

    print(f"  ① canary 分数 ≥ 75%: {fitness_score} → {'✅' if score_ok else '❌'}")
    print(f"  ② 有 canary commit:   {'✅' if has_canary_commit else '❌'}")
    print(f"  ③ diff 只动canary:    {'✅' if diff_clean else '⚠️ (混了其他文件)'}")
    print(f"     涉及文件: {diff_files}")

    all_ok = score_ok and has_canary_commit
    print()

    if all_ok and score_ok:
        print("✅ 三件齐 → 真焊上了！下一步: 找新最弱格")
        print("\n接下来跑: python do_fitness_deep_drill.py")
        return "WELDED_MOVE_ON"
    elif score_ok and not has_canary_commit:
        print("⚠️ 分数涨了但没 commit → 需要补焊")
        print("建议: 手动 git add + commit fitness.json")
        return "SCORE_OK_NO_COMMIT"
    else:
        print("❌ 没焊上 → 写 autopsy 钉根因")
        print("\n建议: python autopsy_canary_80_3x.py")
        return "NOT_WELDED_AUTOPY"

if __name__ == "__main__":
    result = main()
    sys.exit(0 if result == "WELDED_MOVE_ON" else 1)
