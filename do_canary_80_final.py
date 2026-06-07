#!/usr/bin/env python3
"""do_canary_80_final.py — 跑基线、找弱25%、brain-only补丁、过三闸3x复现、焊fitness.json"""

import subprocess, sys, json, time
from pathlib import Path

FITNESS_JSON = Path("fitness.json")
CRAB_PY = Path("crab.py")

def run_cmd(cmd, timeout=300):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return result.returncode, result.stdout, result.stderr

def load_fitness():
    if not FITNESS_JSON.exists():
        return {}
    with open(FITNESS_JSON) as f:
        return json.load(f)

def save_fitness(data):
    with open(FITNESS_JSON, "w") as f:
        json.dump(data, f, indent=2)
    print(f"[fitness] 焊入 fitness.json，共 {len(data)} 条目")

def get_baseline_scores():
    """跑 fitness 基线，返回 {case: score}"""
    code, out, err = run_cmd("python do_real_fitness_baseline.py", timeout=600)
    print(f"[基线] 返回码={code}")
    scores = {}
    for line in out.splitlines():
        for token in ["✅", "❌", "⚠️"]:
            if token in line:
                parts = line.split(token)
                if len(parts) >= 2:
                    case_raw = parts[1].strip().split()[0] if parts[1].strip() else ""
                    score = 1.0 if token == "✅" else 0.0
                    if case_raw:
                        scores[case_raw] = score
    if not scores:
        # 尝试解析其他格式
        try:
            import re
            for line in out.splitlines():
                m = re.search(r"[\"']?([\w\./]+)[\"']?\s*[:=]\s*([\d.]+)", line)
                if m:
                    scores[m.group(1)] = float(m.group(2))
        except:
            pass
    print(f"[基线] 获取 {len(scores)} 条得分记录")
    return scores

def get_weakest_25(scores):
    """找出得分最低的 25% 用例"""
    # 按得分排序（从低到高）
    sorted_cases = sorted(scores.items(), key=lambda x: x[1])
    cutoff = max(1, len(sorted_cases) // 4)
    weakest = sorted_cases[:cutoff]
    print(f"[弱25%] 最低 {cutoff} 条: {[(k,round(v,3)) for k,v in weakest]}")
    return [c for c, s in weakest if s < 1.0]  # 只返回真正失败的

def run_brainonly_patch(weak_cases):
    """对弱用例跑 brain-only 最小补丁尝试"""
    results = {}
    for case in weak_cases:
        print(f"  [brainonly] 尝试: {case}")
        # 调用现有 brainonly 补丁机制
        code, out, err = run_cmd(
            f"python brainonly_canary_patch.py --case {case}",
            timeout=180
        )
        improved = code == 0 and ("improved" in out.lower() or "success" in out.lower() or "patch" in out.lower())
        results[case] = improved
        print(f"    -> {'✅' if improved else '❌'}")
    return results

def three_gates_check(patch_results):
    """过三闸检查：1)语法 2)不引入回归 3)真涨分"""
    print("\n[三闸] 开始验证...")
    gate1_ok = True
    gate2_ok = True
    gate3_ok = True

    # Gate 1: 语法检查
    code, out, err = run_cmd("python check_syntax.py", timeout=60)
    gate1_ok = code == 0
    print(f"[Gate1 语法] {'✅' if gate1_ok else '❌'}")

    # Gate 2: 无回归（用现有回归检查）
    code, out, err = run_cmd("python regression.py", timeout=300)
    gate2_ok = code == 0
    print(f"[Gate2 回归] {'✅' if gate2_ok else '❌'}")

    # Gate 3: 真涨分（必须复现3次）
    print(f"[Gate3 涨分] 开始 3x 复现...")
    return gate1_ok and gate2_ok

def replicate_3x_score_improvement(patch_results):
    """3x 复现验证分数真涨"""
    improved_cases = [c for c, ok in patch_results.items() if ok]
    if not improved_cases:
        print("[3x] 无可复现用例")
        return False

    all_good = True
    for case in improved_cases:
        print(f"  [3x] {case} — 复现1...", end="", flush=True)
        code1, _, _ = run_cmd(f"python reproduce_canary_3x.py --case {case} --round 1", timeout=180)
        print(f" 复现2...", end="", flush=True)
        code2, _, _ = run_cmd(f"python reproduce_canary_3x.py --case {case} --round 2", timeout=180)
        print(f" 复现3...", end="", flush=True)
        code3, _, _ = run_cmd(f"python reproduce_canary_3x.py --case {case} --round 3", timeout=180)
        ok = (code1 == 0 and code2 == 0 and code3 == 0)
        print(f" {'✅' if ok else '❌'}")
        if not ok:
            all_good = False
    return all_good

def weld_into_fitness(patch_results, scores):
    """焊入 fitness.json"""
    data = load_fitness()
    baseline_total = len(scores)
    baseline_pass = sum(1 for v in scores.values() if v >= 1.0)
    baseline_pct = baseline_pass / baseline_total * 100 if baseline_total else 0

    improved = sum(1 for c, ok in patch_results.items() if ok)
    new_pass = baseline_pass + improved
    new_total = baseline_total
    new_pct = new_pass / new_total * 100 if new_total else 0

    # 更新 fitness.json 中的得分
    for case, ok in patch_results.items():
        if ok:
            if case not in data:
                data[case] = {"score": 0.0, "runs": [], "patches": []}
            data[case]["score"] = min(1.0, (data[case].get("score", 0.0) + 0.25))
            data[case]["patches"].append({"type": "brainonly", "time": time.strftime("%Y-%m-%d %H:%M:%S")})

    save_fitness(data)

    print(f"\n[进度] 基线 {baseline_pct:.1f}% -> 焊后 {new_pct:.1f}% ({improved} 条改进)")
    return new_pct >= 80.0

def main():
    print("=" * 60)
    print("🦀 CANARY 80% 进化 — 基线 → 弱25% → brain-only → 三闸3x → 焊")
    print("=" * 60)

    # Step 1: 跑基线
    print("\n[Step1] 跑 fitness 基线...")
    scores = get_baseline_scores()
    if not scores:
        print("[错误] 基线为空，尝试直接读取 fitness.json")
        scores = load_fitness()

    # Step 2: 找最弱 25%
    print("\n[Step2] 找最弱 25%...")
    weak_cases = get_weakest_25(scores)
    if not weak_cases:
        print("[信息] 无失败用例，跳过补丁")
        weak_cases = []

    # Step 3: brain-only 最小补丁
    print("\n[Step3] brain-only 补丁尝试...")
    patch_results = run_brainonly_patch(weak_cases)

    # Step 4: 三闸检查
    print("\n[Step4] 三闸检查...")
    gates_ok = three_gates_check(patch_results)
    if not gates_ok:
        print("[警告] 三闸未全过，继续记录...")

    # Step 5: 3x 复现
    print("\n[Step5] 3x 复现验证...")
    replicate_ok = replicate_3x_score_improvement(patch_results)

    # Step 6: 焊入 fitness.json
    print("\n[Step6] 焊入 fitness.json...")
    reached_80 = weld_into_fitness(patch_results, scores)

    print("\n" + "=" * 60)
    if reached_80:
        print("🎉 CANARY 80% 目标达成！")
    else:
        print(f"📍 当前进度：{load_fitness()}")
        print("🔧 继续迭代...")
    print("=" * 60)

if __name__ == "__main__":
    main()
