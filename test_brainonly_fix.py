#!/usr/bin/env python3
"""验证 brain-only 修复是否有效：3x 复现涨分"""
import subprocess
import sys
import json
import time
from pathlib import Path

def run_and_score(label: str) -> float:
    """运行评估并返回分数"""
    print(f"\n{'='*50}")
    print(f"第 {label} 次运行")
    print('='*50)
    
    result = subprocess.run(
        [sys.executable, "run_fitness_baseline.py"],
        capture_output=True, text=True, timeout=300
    )
    output = result.stdout + result.stderr
    
    # 提取分数
    import re
    scores = []
    for match in re.findall(r'(\d+\.?\d*)%?', output):
        scores.append(float(match))
    
    if scores:
        avg = sum(scores) / len(scores)
        print(f"分数: {avg:.2f}%")
        return avg
    
    # 尝试从 fitness.json 读取
    fitness = Path("fitness.json")
    if fitness.exists():
        with open(fitness) as f:
            data = json.load(f)
        if 'overall' in data:
            return data['overall']
    
    return 0.0

def main():
    print("=== 验证 brain-only 修复 ===")
    
    runs = []
    for i in range(1, 4):
        score = run_and_score(i)
        runs.append(score)
        if i < 3:
            time.sleep(2)  # 短暂延迟
    
    print(f"\n{'='*50}")
    print("结果汇总")
    print('='*50)
    print(f"运行1: {runs[0]:.2f}%")
    print(f"运行2: {runs[1]:.2f}%")
    print(f"运行3: {runs[2]:.2f}%")
    print(f"平均: {sum(runs)/len(runs):.2f}%")
    
    # 检查是否一致（允许小幅波动）
    if max(runs) - min(runs) < 5:  # 波动小于5%视为稳定
        print("\n✓ 分数稳定，可以更新 fitness.json")
        return True
    else:
        print("\n✗ 分数波动过大，需要进一步调试")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
