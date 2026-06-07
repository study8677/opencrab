"""
闭环：四格真分 → brain-only 焊最弱格 → 三遍复现确认
不预设 canary，让数据定山头。
"""
import json
import subprocess
from pathlib import Path
from crab import crab_dir, log


GRID_LABELS = ["correctness", "safety", "efficiency", "resilience"]


def run_4grid_eval() -> dict[str, float]:
    """跑四格评估，返回真实分数字典。"""
    result = subprocess.run(
        ["python", "-m", "run_4grid_eval"],
        capture_output=True, text=True, cwd=crab_dir()
    )
    # 假设输出在 stdout，最后一行是 JSON
    lines = result.stdout.strip().splitlines()
    last = lines[-1]
    return json.loads(last)


def find_weakest(scores: dict[str, float]) -> str:
    """找分数最低的那一格。"""
    return min(scores, key=scores.get)


def brainonly_weld(cell: str) -> dict:
    """brain-only 方式焊一格，返回 {cell, patch, status}。"""
    result = subprocess.run(
        ["python", "-m", "brainonly_canary_patch", "--cell", cell],
        capture_output=True, text=True, cwd=crab_dir()
    )
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        log(f"brainonly_weld 失败: {result.stderr}")
        return {"cell": cell, "status": "failed", "error": result.stderr}


def verify_cell(cell: str) -> float:
    """单格验证，返回分数。"""
    result = subprocess.run(
        ["python", "-m", "run_4grid_eval", "--cell", cell],
        capture_output=True, text=True, cwd=crab_dir()
    )
    lines = result.stdout.strip().splitlines()
    data = json.loads(lines[-1])
    return data.get(cell, 0.0)


def triple_reproduce(cell: str) -> list[float]:
    """三遍复现，返回三个分数。"""
    scores = []
    for i in range(3):
        score = verify_cell(cell)
        scores.append(score)
        log(f"复现 {i+1}/3: {cell} = {score}")
    return scores


def main():
    log("=== 闭环：brain-only 焊最弱格 ===")
    
    # 1. 跑四格真分
    scores = run_4grid_eval()
    log(f"四格真分: {scores}")
    
    # 2. 找最弱格
    weakest = find_weakest(scores)
    weakest_score = scores[weakest]
    log(f"最弱格: {weakest} = {weakest_score}")
    
    # 3. brain-only 焊它
    weld_result = brainonly_weld(weakest)
    log(f"焊接结果: {weld_result}")
    
    # 4. 三遍复现确认
    reproduce_scores = triple_reproduce(weakest)
    avg = sum(reproduce_scores) / len(reproduce_scores)
    
    # 5. 结论
    improved = avg > weakest_score
    log(f"复现结果: {reproduce_scores}, 均值: {avg:.3f}, 提升: {improved}")
    
    if improved:
        log(f"✓ 闭环成功：{weakest} 从 {weakest_score:.3f} 提升到 {avg:.3f}")
    else:
        log(f"✗ 未提升：{weakest} 仍是 {weakest_score:.3f}，需要复查")
    
    return {
        "weakest": weakest,
        "before": weakest_score,
        "after": avg,
        "improved": improved,
        "reproduce": reproduce_scores
    }


if __name__ == "__main__":
    main()
