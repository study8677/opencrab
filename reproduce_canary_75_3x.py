#!/usr/bin/env python3
"""
canary_75 3x 复现验证器
跑3次 fitness baseline，看真涨没涨，再决定焊不焊 fitness.json
"""
import json
import subprocess
import sys
import time
from pathlib import Path

def load_fitness_json():
    p = Path("fitness.json")
    if p.exists():
        return json.loads(p.read_text())
    return {}

def load_baseline():
    p = Path("baseline_scores.json")
    if p.exists():
        return json.loads(p.read_text())
    return {}

def run_single_fitness():
    """跑一次 fitness baseline，返回分数"""
    print("  [1] Running fitness baseline...")
    result = subprocess.run(
        [sys.executable, "run_fitness_baseline.py", "--quick"],
        capture_output=True, text=True, timeout=300
    )
    if result.returncode != 0:
        print(f"  [!] Baseline run failed: {result.stderr[:200]}")
        return None
    
    # 解析输出拿分数
    scores = load_baseline()
    return scores.get("overall", scores.get("fitness", None))

def main():
    print("=" * 60)
    print("CANARY 75  3x 复现验证器")
    print("=" * 60)
    
    # 1. 读当前 fitness.json
    current = load_fitness_json()
    current_score = current.get("fitness", current.get("score", "N/A"))
    print(f"\n[现状] fitness.json 记录: {current_score}")
    
    # 2. 读当前 baseline_scores.json
    baseline = load_baseline()
    baseline_score = baseline.get("overall", baseline.get("fitness", "N/A"))
    print(f"[现状] baseline_scores.json 记录: {baseline_score}")
    
    # 3. 跑3次
    results = []
    for i in range(1, 4):
        print(f"\n--- 第 {i} 次运行 ---")
        score = run_single_fitness()
        if score is not None:
            results.append(score)
            print(f"  → 得分: {score}")
        else:
            print(f"  → 失败，跳过")
        time.sleep(2)
    
    # 4. 分析
    print("\n" + "=" * 60)
    print("3x 复现结果")
    print("=" * 60)
    
    if not results:
        print("[X] 3次全失败，无法判断")
        return
    
    avg = sum(results) / len(results)
    print(f"  3次得分: {results}")
    print(f"  平均得分: {avg:.4f}")
    print(f"  fitness.json 记录: {current_score}")
    print(f"  baseline_scores.json 记录: {baseline_score}")
    
    # 5. 判断
    print("\n" + "=" * 60)
    print("判断")
    print("=" * 60)
    
    # 转换比较
    try:
        current_f = float(current_score)
        baseline_f = float(baseline_score)
        
        delta_vs_fitness = avg - current_f
        delta_vs_baseline = avg - baseline_f
        
        print(f"  avg vs fitness.json: {delta_vs_fitness:+.4f}")
        print(f"  avg vs baseline_scores: {delta_vs_baseline:+.4f}")
        
        # 判定：avg 比当前 fitness.json 高 0.01 以上才算真涨
        if delta_vs_fitness > 0.01:
            print("\n✅ 结论: 真涨了！应该焊 fitness.json")
            print("   建议: 运行 update_fitness_from_run 或类似脚本")
        elif delta_vs_fitness < -0.01:
            print("\n❌ 结论: 没涨反而跌了！需要尸检换山头")
            print("   建议: 先检查 autopsy 相关脚本")
        else:
            print("\n⚠️  结论: 持平，不确定有没有效")
            print("   建议: 再多跑几次或检查其他指标")
            
    except (TypeError, ValueError):
        print(f"\n⚠️  无法比较 (fitness={current_score}, baseline={baseline_score})")
        print("   手动检查输出")

if __name__ == "__main__":
    main()
