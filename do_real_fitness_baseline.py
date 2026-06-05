"""
真适应度基线闭环 - 运行基线、找最弱格、brain-only 改、焊进 fitness.json
"""
import subprocess
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
FITNESS_JSON = REPO_ROOT / "fitness.json"


def run_fitness_baseline():
    """运行基线评测"""
    print("=" * 60)
    print("第一步：运行真适应度基线")
    print("=" * 60)
    result = subprocess.run(
        [sys.executable, "run_fitness_baseline.py", "--quick"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode == 0


def load_baseline_result():
    """加载最新基线结果"""
    latest_path = REPO_ROOT / "evidence" / "baseline" / "latest.json"
    if latest_path.exists():
        with open(latest_path) as f:
            return json.load(f)
    return None


def find_weakest_cells(result):
    """找出最弱的测试格"""
    weakest = []
    
    dims = [
        ("arena", result.get("arena_passed", 0), result.get("arena_total", 0)),
        ("boundaryeval", result.get("boundary_passed", 0), result.get("boundary_total", 0)),
        ("regression", result.get("regression_passed", 0), result.get("regression_total", 0)),
        ("canary", result.get("canary_passed", 0), result.get("canary_total", 0)),
    ]
    
    for name, passed, total in dims:
        if total > 0:
            rate = passed / total
            weakest.append((name, rate, passed, total))
    
    # 按通过率排序，最低的在前
    weakest.sort(key=lambda x: x[1])
    return weakest


def load_fitness_json():
    """加载或初始化 fitness.json"""
    if FITNESS_JSON.exists():
        with open(FITNESS_JSON) as f:
            return json.load(f)
    return {"baseline": {}, "improvements": [], "delta_history": []}


def save_fitness_json(data):
    """保存 fitness.json"""
    with open(FITNESS_JSON, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def brainonly_improve_cell(cell_name):
    """使用 brain-only 方法改进指定格子"""
    print(f"\n第三步：对 {cell_name} 使用 brain-only 改进")
    print("-" * 40)
    
    # 根据格子类型选择合适的 brain-only 工具
    brain_tools = {
        "arena": "patchcourse_brainonly.py",
        "boundaryeval": "brainonly_benefit_chain_regression.py",
        "regression": "brainonly_benefit_review.py",
        "canary": "brainonly_external_validation.py",
    }
    
    tool = brain_tools.get(cell_name)
    if not tool:
        print(f"  ⚠ 没有找到 {cell_name} 对应的 brain-only 工具")
        return False
    
    tool_path = REPO_ROOT / tool
    if not tool_path.exists():
        print(f"  ⚠ 工具 {tool} 不存在，跳过")
        return False
    
    result = subprocess.run(
        [sys.executable, str(tool_path)],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT)
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    return result.returncode == 0


def run_retest_and_compare(cell_name, before_passed, before_total):
    """复测并计算 delta"""
    print(f"\n第四步：复测 {cell_name}")
    print("-" * 40)
    
    # 这里简化为重新运行 baseline
    result = subprocess.run(
        [sys.executable, "run_fitness_baseline.py", "--quick"],
        capture_output=True, text=True,
        cwd=str(REPO_ROOT)
    )
    
    latest = load_baseline_result()
    if latest:
        dim_map = {"arena": "arena", "boundaryeval": "boundaryeval", 
                   "regression": "regression", "canary": "canary"}
        dim = dim_map.get(cell_name, cell_name)
        after_passed = latest.get(f"{dim}_passed", 0)
        after_total = latest.get(f"{dim}_total", 0)
        after_rate = after_passed / max(after_total, 1)
        before_rate = before_passed / max(before_total, 1)
        delta = after_rate - before_rate
        
        print(f"  改进前: {before_passed}/{before_total} ({before_rate:.1%})")
        print(f"  改进后: {after_passed}/{after_total} ({after_rate:.1%})")
        print(f"  Delta:  {delta:+.1%}")
        return delta, after_passed, after_total
    return 0.0, before_passed, before_total


def main():
    # 第一步：运行基线
    run_fitness_baseline()
    
    # 第二步：分析结果找最弱格
    print("\n" + "=" * 60)
    print("第二步：分析基线结果，找最弱格")
    print("=" * 60)
    
    result = load_baseline_result()
    if not result:
        print("⚠ 无法加载基线结果")
        return 1
    
    weakest = find_weakest_cells(result)
    print("\n各维度通过率（从低到高）：")
    for name, rate, passed, total in weakest:
        bar = "█" * int(rate * 20) + "░" * (20 - int(rate * 20))
        print(f"  {name:12s} [{bar}] {rate:.1%} ({passed}/{total})")
    
    if weakest:
        weakest_cell = weakest[0][0]  # 最低的
        weakest_rate = weakest[0][1]
        weakest_passed = weakest[0][2]
        weakest_total = weakest[0][3]
        print(f"\n→ 最弱格: {weakest_cell} ({weakest_rate:.1%})")
        
        # 第三步：brain-only 改进
        improved = brainonly_improve_cell(weakest_cell)
        
        # 第四步：复测并焊进 fitness.json
        if improved:
            delta, after_passed, after_total = run_retest_and_compare(
                weakest_cell, weakest_passed, weakest_total
            )
            
            # 写 fitness.json
            fitness = load_fitness_json()
            
            # 更新 baseline
            fitness["baseline"]["timestamp"] = result.get("timestamp", "")
            fitness["baseline"]["pass_rate"] = result.get("pass_rate", 0)
            
            # 记录这次改进
            improvement = {
                "timestamp": result.get("timestamp", ""),
                "cell": weakest_cell,
                "before": {"passed": weakest_passed, "total": weakest_total},
                "after": {"passed": after_passed, "total": after_total},
                "delta": delta,
                "method": "brain-only"
            }
            fitness["improvements"].append(improvement)
            fitness["delta_history"].append(delta)
            
            save_fitness_json(fitness)
            
            print(f"\n✅ 真 delta 已焊进 fitness.json: {delta:+.1%}")
            print(f"   格子: {weakest_cell}")
            print(f"   从 {weakest_rate:.1%} → {after_passed/max(after_total,1):.1%}")
        else:
            print("\n⚠ brain-only 改进未能成功执行")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
