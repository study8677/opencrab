#!/usr/bin/env python3
"""
闭环验证脚本: fitness测试 → deep_drill找弱 → train_weakness训练 → 复测
确保"测→找弱→练→复测"真正跑通，验证分数是否真涨。
"""
import argparse
import subprocess
import json
import sys
import time
from pathlib import Path

# 相对导入
sys.path.insert(0, str(Path(__file__).parent))

def run_fitness_benchmark(tag: str = "baseline") -> dict:
    """执行fitness基准测试，返回分数结果"""
    print(f"\n{'='*60}")
    print(f"[1/4] 执行 fitness 基准测试 (tag={tag})")
    print(f"{'='*60}")
    
    result = subprocess.run(
        ["python", "-m", "execute_fitness_run", "--tag", tag, "--quiet"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent
    )
    
    if result.returncode != 0:
        print(f"WARN: fitness run failed: {result.stderr}")
        # 尝试解析已有结果
        result_file = Path("fitness_results/latest.json")
        if result_file.exists():
            with open(result_file) as f:
                return json.load(f)
        return {}
    
    # 解析最新结果
    result_file = Path("fitness_results/latest.json")
    if result_file.exists():
        with open(result_file) as f:
            data = json.load(f)
            score = data.get("overall_score", data.get("fitness_score", 0))
            print(f"  → Fitness 分数: {score}")
            return data
    return {}


def run_deep_drill(current_score: float) -> dict:
    """执行deep_drill找出最弱维度"""
    print(f"\n{'='*60}")
    print(f"[2/4] 执行 deep_drill 找出最弱维度")
    print(f"{'='*60}")
    
    result = subprocess.run(
        ["python", "-m", "do_fitness_deep_drill", 
         "--baseline-score", str(current_score),
         "--top-k", "3"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent
    )
    
    # 解析输出找最弱维度
    weakest_dim = None
    weakness_scores = {}
    
    for line in result.stdout.split("\n"):
        if "weakest" in line.lower() and ":" in line:
            try:
                parts = line.split(":")
                dim = parts[0].strip().split()[-1]
                score = float(parts[-1].strip())
                weakness_scores[dim] = score
            except:
                pass
    
    # 找最低分维度
    if weakness_scores:
        weakest_dim = min(weakness_scores, key=weakness_scores.get)
        weakest_score = weakness_scores[weakest_dim]
        print(f"  → 最弱维度: {weakest_dim} (分数: {weakest_score})")
    else:
        # 从stderr或默认逻辑推断
        print(f"  raw output: {result.stdout[:500]}")
        weakest_dim = "unknown"
    
    if result.returncode != 0:
        print(f"WARN: deep_drill issues: {result.stderr}")
    
    return {
        "weakest_dimension": weakest_dim,
        "all_weaknesses": weakness_scores,
        "raw_output": result.stdout
    }


def run_targeted_training(weak_dim: str, iterations: int = 3) -> dict:
    """对最弱维度执行定向训练"""
    print(f"\n{'='*60}")
    print(f"[3/4] 执行 train_weakness 定向训练 (target={weak_dim}, iter={iterations})")
    print(f"{'='*60}")
    
    result = subprocess.run(
        ["python", "-m", "train_weakness",
         "--target-dimension", weak_dim,
         "--iterations", str(iterations),
         "--verbose"],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent
    )
    
    training_success = result.returncode == 0
    print(f"  → 训练{'成功' if training_success else '失败'}")
    
    if not training_success:
        print(f"  stderr: {result.stderr[:200]}")
    
    return {
        "success": training_success,
        "target_dimension": weak_dim,
        "iterations": iterations,
        "output": result.stdout[:500] if result.stdout else "",
        "stderr": result.stderr[:200] if result.stderr else ""
    }


def verify_improvement(baseline_score: float, new_score: float) -> dict:
    """验证分数是否真正提升"""
    delta = new_score - baseline_score
    threshold = 0.01  # 1%提升阈值
    
    improvement = delta > threshold
    significant = delta > 0.05
    
    return {
        "baseline": baseline_score,
        "new": new_score,
        "delta": delta,
        "delta_pct": (delta / baseline_score * 100) if baseline_score > 0 else 0,
        "improved": improvement,
        "significant_improvement": significant,
        "summary": (
            f"✅ 显著提升 +{delta:.4f} ({(delta/baseline_score*100):.1f}%)" if significant else
            f"📈 略有提升 +{delta:.4f}" if improvement else
            f"⚠️ 无明显提升 (Δ={delta:.4f})"
        )
    }


def main():
    parser = argparse.ArgumentParser(description="闭环验证: 测→找弱→练→复测")
    parser.add_argument("--baseline-tag", default="close_loop_baseline", help="基线测试标签")
    parser.add_argument("--post-train-tag", default="close_loop_post_train", help="训练后测试标签")
    parser.add_argument("--training-iterations", type=int, default=3, help="训练迭代次数")
    parser.add_argument("--skip-baseline", action="store_true", help="跳过基线测试(使用已有结果)")
    args = parser.parse_args()
    
    print("\n" + "="*60)
    print("🔄 闭环验证: fitness → deep_drill → train_weakness → 复测")
    print("="*60)
    
    # Step 1: 基线测试
    if args.skip_baseline:
        baseline_data = run_fitness_benchmark("existing")
        baseline_score = baseline_data.get("overall_score", baseline_data.get("fitness_score", 0))
    else:
        baseline_data = run_fitness_benchmark(args.baseline_tag)
        baseline_score = baseline_data.get("overall_score", baseline_data.get("fitness_score", 0))
    
    if baseline_score == 0:
        print("❌ 无法获取基线分数，退出")
        sys.exit(1)
    
    # Step 2: Deep drill找最弱维度
    drill_result = run_deep_drill(baseline_score)
    weak_dim = drill_result.get("weakest_dimension", "unknown")
    
    if weak_dim == "unknown":
        print("⚠️ 无法确定最弱维度，使用默认策略")
        weak_dim = "accuracy"  # fallback
    
    # Step 3: 定向训练
    train_result = run_targeted_training(weak_dim, args.training_iterations)
    
    if not train_result["success"]:
        print("⚠️ 训练可能有问题，继续复测...")
    
    # Step 4: 复测
    print(f"\n{'='*60}")
    print(f"[4/4] 执行复测验证")
    print(f"{'='*60}")
    
    post_data = run_fitness_benchmark(args.post_train_tag)
    post_score = post_data.get("overall_score", post_data.get("fitness_score", 0))
    
    if post_score == 0:
        print("❌ 无法获取复测分数")
        sys.exit(1)
    
    # 验证结果
    verification = verify_improvement(baseline_score, post_score)
    
    # 打印完整报告
    print(f"\n{'='*60}")
    print("📊 闭环验证报告")
    print(f"{'='*60}")
    print(f"基线分数:     {verification['baseline']:.4f}")
    print(f"复测分数:     {verification['new']:.4f}")
    print(f"提升幅度:     {verification['delta']:+.4f} ({verification['delta_pct']:+.2f}%)")
    print(f"最弱维度:     {weak_dim}")
    print(f"训练迭代:     {args.training_iterations}")
    print(f"{'='*60}")
    print(verification['summary'])
    print(f"{'='*60}")
    
    # 保存报告
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "baseline_score": baseline_score,
        "post_train_score": post_score,
        "weakest_dimension": weak_dim,
        "training_iterations": args.training_iterations,
        "verification": verification,
        "close_loop_success": verification['improved']
    }
    
    report_file = Path("close_loop_report.json")
    with open(report_file, "w") as f:
        json.dump(report, f, indent=2)
    print(f"\n报告已保存: {report_file}")
    
    # 退出码反映成功与否
    sys.exit(0 if verification['improved'] else 1)


if __name__ == "__main__":
    main()
