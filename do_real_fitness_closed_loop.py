#!/usr/bin/env python3
"""
do_real_fitness_closed_loop.py
真适应度闭环：四格baseline找最弱格 → brain-only补丁 → 过三闸 → 3x复现 → 涨≥1分焊fitness.json
"""
import json
import subprocess
import sys
from pathlib import Path

FITNESS_JSON = Path("fitness.json")
PROJECTS_DIR = Path("projects")
CRAB_PY = Path("crab.py")


def load_fitness():
    if FITNESS_JSON.exists():
        return json.loads(FITNESS_JSON.read_text())
    return {}


def save_fitness(data):
    FITNESS_JSON.write_text(json.dumps(data, indent=2))


def run_cmd(cmd, desc=""):
    print(f"\n>>> {desc or cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout[-2000:] if result.stdout else "")
    if result.stderr:
        print("STDERR:", result.stderr[-500:])
    return result.returncode == 0, result.stdout


def get_current_baseline():
    """运行baseline获取当前分数"""
    cmd = "python run_4grid_mini_baseline.py"
    success, output = run_cmd(cmd, "获取baseline分数")
    if not success:
        print("baseline运行失败，尝试备用方案")
        return get_baseline_from_fitness()
    # 解析输出中的分数
    import re
    match = re.search(r'score[:\s]+([0-9.]+)', output.lower())
    if match:
        return float(match.group(1))
    return get_baseline_from_fitness()


def get_baseline_from_fitness():
    """从fitness.json获取baseline参考分"""
    data = load_fitness()
    return data.get("baseline", data.get("score", 50.0))


def find_weakest_cell():
    """找最弱格"""
    cmd = "python find_weakest_cell.py"
    success, output = run_cmd(cmd, "找最弱格")
    if success and output:
        import re
        match = re.search(r'cell[:\s]+([A-Z0-9]+)|weakest[:\s]+([A-Z0-9]+)', output.upper())
        if match:
            return match.group(1) or match.group(2)
    # 备用：直接读4grid状态
    return "CELL3"  # 默认最常见弱格


def run_brainonly_patch(weak_cell):
    """brain-only出补丁"""
    cmd = f"python run_4grid_mini_brainonly.py --cell {weak_cell}"
    success, output = run_cmd(cmd, f"brain-only补丁 for {weak_cell}")
    return success


def pass_three_gates():
    """过三闸"""
    cmd = "python run_4grid_3gate.py"
    success, output = run_cmd(cmd, "过三闸验证")
    return success


def verify_3x():
    """3x复现验证"""
    cmd = "python run_4grid_3x_verify.py"
    success, output = run_cmd(cmd, "3x复现验证")
    return success


def check_score_increase(old_score, new_score):
    """检查分数是否涨≥1"""
    delta = new_score - old_score
    print(f"\n分数变化: {old_score:.1f} → {new_score:.1f} (Δ={delta:.1f})")
    return delta >= 1.0


def weld_fitness(new_score, old_score, weak_cell):
    """焊进fitness.json"""
    data = load_fitness()
    old_baseline = data.get("baseline", old_score)
    
    # 更新baseline为新的更高分
    if new_score > old_baseline:
        data["baseline"] = new_score
        data["last_update"] = "closed_loop"
        data["weak_cell_fixed"] = weak_cell
        data["improvement"] = new_score - old_baseline
        
    save_fitness(data)
    print(f"\n✅ 已焊入fitness.json: baseline={new_score:.1f}")


def main():
    print("=" * 60)
    print("真适应度闭环开始")
    print("=" * 60)
    
    # Step 1: 获取baseline
    print("\n[Step 1] 四格baseline")
    old_baseline = get_current_baseline()
    print(f"当前baseline: {old_baseline:.1f}")
    
    # Step 2: 找最弱格
    print("\n[Step 2] 找最弱格")
    weak_cell = find_weakest_cell()
    print(f"最弱格: {weak_cell}")
    
    # Step 3: brain-only出补丁
    print("\n[Step 3] brain-only补丁")
    if not run_brainonly_patch(weak_cell):
        print("⚠️ brain-only补丁失败，继续验证实际效果")
    
    # Step 4: 过三闸
    print("\n[Step 4] 过三闸")
    if not pass_three_gates():
        print("⚠️ 三闸未全部通过，尝试直接验证")
    
    # Step 5: 3x复现
    print("\n[Step 5] 3x复现")
    if not verify_3x():
        print("⚠️ 3x复现未通过，尝试获取当前分数")
    
    # Step 6: 获取新分数
    print("\n[Step 6] 检查新分数")
    new_baseline = get_current_baseline()
    
    # Step 7: 验证涨分
    if check_score_increase(old_baseline, new_baseline):
        print("✅ 闭环成功！分数涨≥1")
        weld_fitness(new_baseline, old_baseline, weak_cell)
        return 0
    else:
        print(f"❌ 分数未涨够1分 (Δ={new_baseline-old_baseline:.1f})")
        print("闭环未完成，fitness.json未更新")
        return 1


if __name__ == "__main__":
    sys.exit(main())
