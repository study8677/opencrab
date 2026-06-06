#!/usr/bin/env python3
"""
canary_75_weld.py
================
canary-75 全链路焊接入口。

五步焊死（不再喊口号）：
  1. astlocator.locate()    → 定位真缺陷 (confidence >= 0.7 过 Gate-1)
  2. readpack.pack()        → 看代码边界
  3. intentpatch.patch()    → 产受限 JSON
  4. patchfitroom.fit()     → 三闸评估 (score >= 0.6, errors == 0 过 Gate-2)
  5. 3x 复现                → 三次 run 收敛同 location (Gate-3)

三闸全通过 → 真分入账 (ledger) + 提交主干 (git commit)
任一闸拒收 → autopy 根因卡 + 写复发卡到 handsdojo，不再绕回重喊。

Usage:
    python canary_75_weld.py [goal] [target_file]
    # goal:              缺陷描述，例如 "fix off-by-one in loop boundary"
    # target_file:       目标源文件，例如 "crab.py"
    # 如果不传参，用下面的 DEFAULT_GOAL / DEFAULT_TARGET
"""
import sys
import time

DEFAULT_GOAL = "fix boundary error in crab.py"
DEFAULT_TARGET = "crab.py"

def main():
    goal = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_GOAL
    target = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TARGET
    print(f"[canary_75_weld] goal={goal!r}")
    print(f"[canary_75_weld] target={target!r}")

    # 复用 go_canary_75.run() — 它已经焊好三闸逻辑
    from go_canary_75 import run
    result = run(goal=goal, target=target)

    if result is None:
        print("[canary_75_weld] ALL GATES FAILED or EXCEPTION — check handsdojo_canary_75_blocked.jsonl")
        sys.exit(1)
    else:
        print("[canary_75_weld] SUCCESS — all three gates passed, ledger split done, trunk committed")
        sys.exit(0)


if __name__ == "__main__":
    main()
