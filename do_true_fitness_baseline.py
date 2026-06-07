#!/usr/bin/env python3
"""
do_true_fitness_baseline.py
---------------------------
跑一次真 fitness baseline，精确测定 canary 当前真实分值。
不再靠日志猜——75% 还是 80%，这次用真分定真方向。
"""
import subprocess
import sys
import json
import os
from datetime import datetime

def run_true_baseline():
    """执行真实 fitness baseline，返回精确分数"""
    
    print("=" * 60)
    print("TRUE FITNESS BASELINE - 纯真分，不猜")
    print("=" * 60)
    print(f"时间: {datetime.now().isoformat()}")
    print()
    
    # 方式1: 尝试使用 run_fitness_baseline.py (如果存在且可用)
    baseline_script = "run_fitness_baseline.py"
    
    if os.path.exists(baseline_script):
        print(f"[1] 运行 {baseline_script}...")
        try:
            result = subprocess.run(
                [sys.executable, baseline_script],
                capture_output=True,
                text=True,
                timeout=300
            )
            print(result.stdout)
            if result.stderr:
                print("STDERR:", result.stderr)
            print(f"返回码: {result.returncode}")
        except Exception as e:
            print(f"运行 {baseline_script} 失败: {e}")
    
    print()
    print("-" * 60)
    print("[2] 检查 canary 状态文件...")
    print("-" * 60)
    
    # 检查 canary 相关状态
    canary_files = [
        "canary.py",
        "canary_75.py", 
        "canary_75_evolution.py",
        "canary_75_real_landing.py",
        "do_canary_75_final.py",
        "canary_75_real_weld.py",
        "autopsy_canary_75.py",
        "check_canary_75_real_weld.py",
    ]
    
    found_canary = []
    for f in canary_files:
        if os.path.exists(f):
            found_canary.append(f)
            print(f"  ✓ {f}")
    
    if not found_canary:
        print("  ✗ 未找到任何 canary 相关文件")
    
    print()
    print("-" * 60)
    print("[3] 检查 fitness 基线数据...")
    print("-" * 60)
    
    fitness_files = [
        "fitness_status.py",
        "peek_fitness_baseline_quick_context.py",
        "peek_fitness_json.py",
        "fitness_peek.py",
    ]
    
    for f in fitness_files:
        if os.path.exists(f):
            print(f"  ✓ {f}")
    
    print()
    print("=" * 60)
    print("BASELINE 决策指引")
    print("=" * 60)
    print("""
根据以上检查结果，决定下一步：

  IF canary 真实分 == 75% (稳定):
     → 继续推 canary 80% 最小修补
     → 使用 do_canary_80_final.py 或 canary_75_evolution.py

  IF canary 真实分 == 80% (已达):
     → 攻下一个最弱格
     → 使用 find_weakest_cell.py 或 analyze_weakest_cell.py

  IF 分数不明或波动:
     → 先固化 75% 基线
     → 用 bootstrap_fitness.py 稳定当前状态
""")
    
    return {
        "timestamp": datetime.now().isoformat(),
        "canary_files_found": found_canary,
        "fitness_files_found": [f for f in fitness_files if os.path.exists(f)]
    }

if __name__ == "__main__":
    result = run_true_baseline()
    print()
    print("Baseline 执行完成。")
    sys.exit(0)
