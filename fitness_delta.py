#!/usr/bin/env python3
"""Quick delta view: compare current fitness.json with previous snapshot - 四格版"""
import json
import sys
from pathlib import Path

def load_fitness(path):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            print(f"[fitness_delta] could not load {path}: {e}")
    return None

def show_heatmap(cells):
    """打印四格热力图"""
    print("=== 四格热力图 ===")
    for name in ["arena", "boundaryeval", "regression", "canary"]:
        cell = cells.get(name, {})
        score = cell.get("score", 0.0)
        bar = "█" * int(score * 10) + "░" * (10 - int(score * 10))
        icon = "●" if cell.get("success") else "○"
        summary = cell.get("summary", "")[:50]
        print(f"  {icon} [{name:12}] {bar} {score:.2f}  {summary}")

def main():
    state_dir = Path("state")
    fitness_path = state_dir / "fitness.json"
    history_path = state_dir / "fitness_history.json"

    current = load_fitness(fitness_path)
    history = load_fitness(history_path) or []

    if not current:
        print("[fitness_delta] no current fitness data — run run_fitness_baseline_quick.py first")
        sys.exit(1)

    # show current snapshot
    print("=== CURRENT FITNESS ===")
    ts = current.get("timestamp", "?")
    hb = current.get("heartbeat", "?")
    print(f"  timestamp: {ts}  heartbeat: #{hb}")
    comp = current.get("composite", 0)
    passed = int(comp * 4)
    print(f"  composite score: {comp:.2f} ({passed}/4 passed)")

    # 兼容新旧格式: cells 或旧的 top-level keys
    cells = current.get("cells", current)

    # 打印热力图
    show_heatmap(cells)

    # 打印每格详情
    print("\n=== 四格详情 ===")
    for name in ["arena", "boundaryeval", "regression", "canary"]:
        cell = cells.get(name, {})
        icon = "●" if cell.get("success") else "○"
        score = cell.get("score", 0.0)
        summary = cell.get("summary", "N/A")
        elapsed = cell.get("elapsed", 0.0)
        print(f"  {icon} {name}: score={score:.2f} elapsed={elapsed:.1f}s")
        print(f"     {summary[:120]}")

    # delta vs previous in history
    if history:
        prev = history[-1]
        print("\n=== DELTA vs PREVIOUS ===")
        p_comp = prev.get("composite", 0)
        delta = comp - p_comp
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        print(f"  composite: {p_comp:.2f} {arrow} {comp:.2f} (Δ={delta:+.2f})")

        prev_cells = prev.get("cells", prev)

        moving = []  # 真在动的格
        stagnant = []  # 原地的格

        for metric in ["arena", "boundaryeval", "regression", "canary"]:
            p_cell = prev_cells.get(metric, {})
            c_cell = cells.get(metric, {})

            p_ok = p_cell.get("success")
            c_ok = c_cell.get("success")
            p_score = p_cell.get("score", 0.0)
            c_score = c_cell.get("score", 0.0)
            score_delta = c_score - p_score

            if p_ok is None and c_ok is None:
                continue

            icon = "●"
            delta_str = "unchanged"
            status = "STAGNANT"

            if c_ok and not p_ok:
                icon = "○→●"
                delta_str = "IMPROVED"
                status = "MOVING"
            elif not c_ok and p_ok:
                icon = "●→○"
                delta_str = "REGRESSED"
                status = "MOVING"
            elif abs(score_delta) > 0.01:
                delta_str = f"score {p_score:.2f}→{c_score:.2f} (Δ={score_delta:+.2f})"
                status = "MOVING"
            else:
                status = "STAGNANT"

            if status == "MOVING":
                moving.append(metric)
            else:
                stagnant.append(metric)

            print(f"  {icon} {metric}: {delta_str}")

        print("\n=== 诊断结论 ===")
        if moving:
            print(f"  真在动: {', '.join(moving)}")
        else:
            print("  真在动: (无) — 所有格原地!")
        if stagnant:
            print(f"  原 地: {', '.join(stagnant)}")

        if stagnant:
            weakest = stagnant[0]  # 挑第一个原地格下刀
            print(f"\n  >>> 建议对 {weakest} 格下刀 (brain-only patch)")

    # append to history
    history.append({
        "timestamp": ts,
        "heartbeat": hb,
        "composite": comp,
        "cells": cells,
    })
    with open(history_path, "w") as f:
        json.dump(history[-10:], f, indent=2)  # keep last 10
    print(f"\n[已追加到历史, 共{len(history)}条记录]")

if __name__ == "__main__":
    main()
