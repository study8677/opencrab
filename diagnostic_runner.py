#!/usr/bin/env python3
"""快速跑 fitness baseline，返回各模块得分排行"""
import subprocess
import sys
import json
from pathlib import Path

def run_fitness_baseline():
    result = subprocess.run(
        [sys.executable, "run_fitness_baseline.py"],
        capture_output=True, text=True, timeout=300
    )
    return result.stdout + result.stderr

if __name__ == "__main__":
    print("=== 运行 run_fitness_baseline ===")
    output = run_fitness_baseline()
    print(output)
    
    # 尝试解析输出找分数
    lines = output.split("\n")
    scores = {}
    for line in lines:
        for keyword in ["boundaryeval", "regression", "arena"]:
            if keyword in line.lower() and any(c.isdigit() for c in line):
                # 提取可能的分数
                import re
                nums = re.findall(r'\d+\.?\d*%?', line)
                if nums:
                    scores[keyword] = nums[-1]
    
    print("\n=== 分数提取 ===")
    print(json.dumps(scores, indent=2))
    print("\n=== 完整输出 ===")
    print(output)
