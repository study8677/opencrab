#!/usr/bin/env python3
"""
放下 canary 死循环，跑 4 格真基线找最弱格，brain-only 焊链验证。
"""
import subprocess
import json
import sys
from pathlib import Path

def run_cmd(cmd, desc):
    print(f"\n>>> {desc}")
    print(f"    {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout[-500:] if len(result.stdout) > 500 else result.stdout)
    if result.returncode != 0:
        print(f"STDERR: {result.stderr[-300:]}")
    return result

def main():
    print("=== 放下 canary 80，跑 4 格真基线找最弱格 ===")

    # 1. 跑 4 格真基线（用 4grid_evolvable_mini 或 run_4grid_mini_baseline）
    # 先检查是否有 fitness baseline
    run_cmd(
        "python -c \"from fitness import get_fitness; print(get_fitness())\"",
        "检查 fitness 状态"
    )

    # 2. 跑 4 格基线
    result = run_cmd(
        "python run_4grid_mini_baseline.py 2>&1 | tail -50",
        "跑 4 格真基线"
    )

    if result.returncode != 0:
        print("基线失败，尝试备用方案...")
        result = run_cmd(
            "python -c \"from run_4grid_3gate import run; run()\" 2>&1 | tail -50",
            "跑 4 格 3 门基线"
        )

    # 3. 找最弱格
    weakest = run_cmd(
        "python -c \"from find_weakest_cell import find_weakest; r=find_weakest(); print(json.dumps(r, indent=2))\"",
        "找最弱格"
    )

    # 4. 如果有最弱格，用 brain-only 焊链
    if weakest.returncode == 0 and weakest.stdout.strip():
        try:
            info = json.loads(weakest.stdout)
            cell = info.get('cell') or info.get('weakest')
            print(f"\n>>> 最弱格: {cell}")
            
            # 尝试 brain-only 焊链
            weld_result = run_cmd(
                f"python grid_brainonly_weld.py --cell {cell} 2>&1 | tail -30",
                f"brain-only 焊链最弱格 {cell}"
            )
            
            if weld_result.returncode == 0 and '涨' in weld_result.stdout.lower():
                print("\n>>> 涨了！commit 记录")
                run_cmd(f"git add -A && git commit -m 'WELD: 4grid brain-only fix {cell}'", "提交")
            else:
                print("\n>>> 没涨或失败，记录卡点")
                with open("CARD_BLOCKER_4GRID.txt", "a") as f:
                    from datetime import datetime
                    f.write(f"{datetime.now()} | cell={cell} | no growth\n")
        except json.JSONDecodeError:
            print(f"无法解析最弱格: {weakest.stdout}")
    else:
        print("未找到最弱格信息")

if __name__ == "__main__":
    main()
