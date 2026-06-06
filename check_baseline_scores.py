#!/usr/bin/env python3
"""检查当前 baseline 分数，找出最弱模块"""
import json
import subprocess
import sys
from pathlib import Path

def main():
    # 尝试读取 fitness.json
    fitness_file = Path("fitness.json")
    if fitness_file.exists():
        with open(fitness_file) as f:
            fitness = json.load(f)
        print("=== 当前 fitness.json ===")
        print(json.dumps(fitness, indent=2))
    
    # 运行 run_fitness_baseline
    print("\n=== 运行 run_fitness_baseline ===")
    result = subprocess.run(
        [sys.executable, "run_fitness_baseline.py"],
        capture_output=True, text=True, timeout=300
    )
    output = result.stdout + result.stderr
    print(output[:5000])  # 限制输出
    
    # 尝试提取分数
    import re
    patterns = {
        "boundaryeval": r"boundaryeval[:\s]+(\d+\.?\d*)",
        "regression": r"regression[:\s]+(\d+\.?\d*)",
        "arena": r"arena[:\s]+(\d+\.?\d*)",
        "boundaryeval_regression": r"boundaryeval_regression[:\s]+(\d+\.?\d*)",
    }
    
    scores = {}
    for name, pattern in patterns.items():
        matches = re.findall(pattern, output, re.IGNORECASE)
        if matches:
            scores[name] = [float(m) for m in matches]
    
    print("\n=== 提取的分数 ===")
    print(json.dumps(scores, indent=2))
    
    # 找最弱的
    if scores:
        weakest = min(scores.items(), key=lambda x: min(x[1]) if x[1] else 999)
        print(f"\n最弱模块: {weakest[0]} (分数: {weakest[1]})")
    
    return scores if scores else None

if __name__ == "__main__":
    scores = main()
    if not scores:
        print("未提取到分数，检查 run_fitness_baseline.py 输出")
        sys.exit(1)
