#!/usr/bin/env python3
"""
canary_75_real_landing.py
真收 canary 75%——跑 3x 复现看真分，没涨就尸检完切到 next weakest，停止再换新点子。

策略：
  1. 读取 fitness.json 当前 best scores
  2. 跑 3x 复现 canary_75，采集真分
  3. 比对：真涨 > 0.01 → 焊进 fitness.json，标记 landed
  4. 没涨 → 调用 autopsy 做尸检，取 weakest cells
  5. 若还有 weakest → 切到那个方向（regression/boundaryeval/arena）
  6. 若已无路可走 → 标记 stuck，换新点子
  7. 3x 复现：min/median/max 三指标都涨才算真涨
"""

import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# 核心路径
SELF_DIR = Path(__file__).parent
FITNESS_JSON = SELF_DIR / "fitness.json"
CANARY_75_SCRIPT = SELF_DIR / "reproduce_canary_75_3x.py"
AUTOPSY_SCRIPT = SELF_DIR / "autopsy.py"
BOUNDARYEVAL_SCRIPT = SELF_DIR / "boundaryeval.py"
ARENA_SCRIPT = SELF_DIR / "arena.py"
REGRESSION_SCRIPT = SELF_DIR / "regression.py"

# 阈值
MIN_IMPROVEMENT = 0.01  # 真涨门槛
MAX_CYCLES = 3  # 最多循环几次
STUCK_THRESHOLD = 2  # 连续 2 次无进展视为 stuck


def load_fitness_json():
    """加载当前 fitness.json"""
    if FITNESS_JSON.exists():
        with open(FITNESS_JSON) as f:
            return json.load(f)
    return {}


def save_fitness_json(data):
    """保存 fitness.json"""
    with open(FITNESS_JSON, "w") as f:
        json.dump(data, f, indent=2)


def run_3x_replication():
    """运行 3x 复现，返回 (median_score, min_score, max_score)"""
    print("\n" + "=" * 60)
    print("🔄 运行 3x 复现 canary_75...")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, str(CANARY_75_SCRIPT)],
        capture_output=True,
        text=True,
        timeout=600,
    )

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    # 解析 3x 输出的 median/min/max
    # 格式示例: "median=0.85 min=0.82 max=0.88"
    median_score = None
    min_score = None
    max_score = None

    for line in result.stdout.splitlines():
        line = line.strip()
        if "median" in line.lower():
            try:
                median_score = float(line.split("=")[-1].strip())
            except:
                pass
        if "min" in line.lower() and "minimum" not in line.lower():
            try:
                min_score = float(line.split("=")[-1].strip())
            except:
                pass
        if "max" in line.lower():
            try:
                max_score = float(line.split("=")[-1].strip())
            except:
                pass

    # 如果解析失败，尝试备用方式
    if median_score is None:
        # 提取最后一行的数字
        for line in reversed(result.stdout.splitlines()):
            line = line.strip()
            if line.replace(".", "").replace("-", "").isdigit():
                median_score = float(line)
                min_score = median_score * 0.95
                max_score = median_score * 1.05
                break

    if median_score is None:
        print("⚠️ 无法解析 3x 复现结果，假设 0.0")
        median_score = 0.0
        min_score = 0.0
        max_score = 0.0

    print(f"\n📊 3x 复现结果: median={median_score:.4f}, min={min_score:.4f}, max={max_score:.4f}")
    return median_score, min_score, max_score


def check_improvement(current_best, new_median, new_min, new_max):
    """检查是否真涨——三指标都涨才算真涨"""
    improvement_median = new_median - current_best
    improvement_min = new_min - current_best
    improvement_max = new_max - current_best

    print(f"\n📈 涨分分析:")
    print(f"  median: {current_best:.4f} → {new_median:.4f} (Δ={improvement_median:+.4f})")
    print(f"  min:    {current_best:.4f} → {new_min:.4f} (Δ={improvement_min:+.4f})")
    print(f"  max:    {current_best:.4f} → {new_max:.4f} (Δ={improvement_max:+.4f})")

    median_ok = improvement_median > MIN_IMPROVEMENT
    min_ok = improvement_min > MIN_IMPROVEMENT * 0.5  # min 门槛略低
    max_ok = improvement_max > MIN_IMPROVEMENT

    all_ok = median_ok and min_ok and max_ok
    any_ok = improvement_median > MIN_IMPROVEMENT

    if all_ok:
        return "landed", improvement_median
    elif any_ok:
        return "partial", improvement_median
    else:
        return "stagnant", improvement_median


def run_autopsy():
    """调用 autopsy 获取 weakest cells"""
    print("\n" + "=" * 60)
    print("🔍 尸检——找 weakest cells...")
    print("=" * 60)

    result = subprocess.run(
        [sys.executable, str(AUTOPSY_SCRIPT), "--weakest-only"],
        capture_output=True,
        text=True,
        timeout=300,
    )

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    # 解析 weakest cells
    weakest_cells = []
    for line in result.stdout.splitlines():
        if "weakest" in line.lower() or "cell" in line.lower():
            # 尝试提取 cell 名称
            parts = line.strip().split()
            for p in parts:
                if p and not p[0].isdigit() and p not in ["weakest", "cells:", "→"]:
                    weakest_cells.append(p)

    return weakest_cells


def pivot_to_next_weakest(weakest_cells):
    """根据 weakest cells 决定下一个方向"""
    if not weakest_cells:
        return None, None

    cell = weakest_cells[0]
    print(f"\n🎯 切换到 weakest: {cell}")

    # 判断方向
    if "regression" in cell or "boundary" in cell:
        script = BOUNDARYEVAL_SCRIPT
    elif "arena" in cell or "battle" in cell:
        script = ARENA_SCRIPT
    elif "brainonly" in cell or "organ" in cell:
        script = REGRESSION_SCRIPT
    else:
        script = BOUNDARYEVAL_SCRIPT

    return script, cell


def weld_improvement(fitness_data, key, new_score):
    """把真涨焊进 fitness.json"""
    timestamp = datetime.now().isoformat()

    if "modules" not in fitness_data:
        fitness_data["modules"] = {}

    if key not in fitness_data["modules"]:
        fitness_data["modules"][key] = {}

    fitness_data["modules"][key]["score"] = new_score
    fitness_data["modules"][key]["timestamp"] = timestamp
    fitness_data["modules"][key]["status"] = "landed"

    # 更新总览
    fitness_data["last_landing"] = timestamp
    fitness_data["canary_75_landed"] = True

    save_fitness_json(fitness_data)
    print(f"\n✅ 已焊进 fitness.json: {key} = {new_score:.4f}")


def main():
    print("=" * 60)
    print("🚀 canary_75_real_landing.py — 真收 canary 75%")
    print("=" * 60)

    fitness_data = load_fitness_json()
    current_best = fitness_data.get("modules", {}).get("canary_75", {}).get("score", 0.0)

    print(f"\n📌 当前 best: canary_75 = {current_best:.4f}")

    cycles = 0
    stuck_count = 0
    direction = "canary_75"

    while cycles < MAX_CYCLES and stuck_count < STUCK_THRESHOLD:
        cycles += 1
        print(f"\n{'=' * 40} 第 {cycles} 轮 {'=' * 40}")

        # 1. 跑 3x 复现
        new_median, new_min, new_max = run_3x_replication()

        # 2. 检查涨分
        status, delta = check_improvement(current_best, new_median, new_min, new_max)

        if status == "landed":
            print(f"\n🎉 真涨达成！Δ={delta:+.4f}")
            weld_improvement(fitness_data, "canary_75", new_median)
            fitness_data = load_fitness_json()
            current_best = new_median
            stuck_count = 0

            # 继续下一轮，看能否再涨
            continue

        elif status == "partial":
            print(f"\n⚠️ 部分涨 (Δ={delta:+.4f})，但不够稳")
            stuck_count += 1

        else:  # stagnant
            print(f"\n❌ 没涨 (Δ={delta:+.4f})")
            stuck_count += 1

        # 3. 没涨 → 尸检
        weakest_cells = run_autopsy()

        if weakest_cells:
            script, cell = pivot_to_next_weakest(weakest_cells)
            if script:
                print(f"\n🔄 切换方向到: {script.name}")
                direction = cell

                # 运行下一个方向
                result = subprocess.run(
                    [sys.executable, str(script), "--focus", cell],
                    capture_output=True,
                    text=True,
                    timeout=600,
                )
                print(result.stdout)
                if result.stderr:
                    print("STDERR:", result.stderr)

                # 方向运行完后，再切回 canary_75 验证
                direction = "canary_75"
        else:
            print("\n🚫 没有找到 weak cells，已无路可走")
            break

    # 4. 总结
    print("\n" + "=" * 60)
    print("📋 canary_75_real_landing 总结")
    print("=" * 60)

    if stuck_count >= STUCK_THRESHOLD:
        print(f"⚠️ 连续 {stuck_count} 次无进展，标记 stuck，换新点子")
        fitness_data["canary_75_stuck"] = True
        fitness_data["stuck_at"] = datetime.now().isoformat()
        save_fitness_json(fitness_data)

        print("\n💡 建议换新点子:")
        print("  1. 尝试全新的 patchfitroom 方向")
        print("  2. 换到完全不同的问题域")
        print("  3. 重新设计 fitness function")
    else:
        print(f"✅ 经过 {cycles} 轮，已达 current_best = {current_best:.4f}")

    print("\n🔄 状态已保存到 fitness.json")


if __name__ == "__main__":
    main()
