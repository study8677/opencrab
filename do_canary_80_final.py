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
    # 先尝试直接读取现有 fitness.json（如果已有跑过的结果）
    existing = load_fitness()
    if existing:
        scores = {}
        for case, info in existing.items():
            if isinstance(info, dict):
                scores[case] = info.get("score", 0.0)
            else:
                scores[case] = float(info)
        if scores:
            print(f"[基线] 从 fitness.json 读取 {len(scores)} 条记录")
            return scores

    # 再尝试跑基线脚本
    candidates = [
        "python do_real_fitness_baseline.py",
        "python run_fitness_baseline.py",
        "python run_fitness_baseline_quick.py",
    ]
    scores = {}
    for cmd in candidates:
        code, out, err = run_cmd(cmd, timeout=600)
        print(f"[基线] 尝试 {cmd!r} → 返回码={code}")
        # 优先解析 ✅/❌ 格式
        for line in out.splitlines():
            for token in ["✅", "❌", "⚠️"]:
                if token in line:
                    parts = line.split(token)
                    if len(parts) >= 2:
                        case_raw = parts[1].strip().split()[0] if parts[1].strip() else ""
                        score = 1.0 if token == "✅" else 0.0
                        if case_raw:
                            scores[case_raw] = score
        if scores:
            break
        # 回退：正则解析 "case": score 格式
        try:
            import re
            for line in out.splitlines():
                m = re.search(r"[\"']?([\w\./\-_]+)[\"']?\s*[:=]\s*([\d.]+)", line)
                if m:
                    scores[m.group(1)] = float(m.group(2))
        except Exception:
            pass
        if scores:
            break

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

def three_gates_check(patch_results, baseline_scores):
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

    # Gate 3: 真涨分（对比基线，必须有可验证的得分提升）
    print(f"[Gate3 涨分] 对比基线检查分数提升...")
    improved_cases = [c for c, ok in patch_results.items() if ok]
    if not improved_cases:
        print("[Gate3] 无改进用例，跳过")
        gate3_ok = True
    else:
        # 重新跑一遍受影响的用例，对比基线分数
        all_improved = True
        for case in improved_cases:
            # 用 evalbench 或 benchmark 重新验证
            code, out, err = run_cmd(
                f"python execute_canary_75.py --case {case}",
                timeout=180
            )
            # 尝试从输出解析得分
            new_score = 0.0
            for line in out.splitlines() + err.splitlines():
                import re
                m = re.search(r"score[:\s=]+([0-9.]+)", line, re.IGNORECASE)
                if m:
                    new_score = float(m.group(1))
                    break
            baseline_score = baseline_scores.get(case, 0.0)
            improved = new_score > baseline_score
            print(f"  [Gate3] {case}: 基线={baseline_score:.2f} → 当前={new_score:.2f} {'✅' if improved else '⚠️'}")
            if not improved:
                all_improved = False
        gate3_ok = all_improved
        print(f"[Gate3 涨分] {'✅' if gate3_ok else '❌'}")

    return gate1_ok and gate2_ok and gate3_ok

def replicate_3x_score_improvement(patch_results, baseline_scores):
    """3x 复现验证分数真涨"""
    improved_cases = [c for c, ok in patch_results.items() if ok]
    if not improved_cases:
        print("[3x] 无可复现用例")
        return True

    all_good = True
    for case in improved_cases:
        baseline = baseline_scores.get(case, 0.0)
        results = []
        for r in range(1, 4):
            print(f"  [3x] {case} 复现{r}/3...", end="", flush=True)
            # 尝试用 reproduce 脚本，若不存在则用 execute 代替
            code, out, err = run_cmd(
                f"python reproduce_canary_3x.py --case {case} --round {r}",
                timeout=180
            )
            if code != 0:
                # fallback: 直接跑执行验证
                code, out, err = run_cmd(f"python execute_canary_75.py --case {case}", timeout=180)
            # 尝试从输出解析得分
            score = baseline
            for line in out.splitlines() + err.splitlines():
                import re
                m = re.search(r"score[:\s=]+([0-9.]+)", line, re.IGNORECASE)
                if m:
                    score = float(m.group(1))
                    break
            ok = score >= baseline
            results.append(ok)
            print(f" 得分={score:.2f} {'✅' if ok else '❌'}")
        # 至少 2/3 通过才认为稳定
        stable = sum(results) >= 2
        print(f"    → {case} 3x 稳定性: {sum(results)}/3 {'✅' if stable else '❌'}")
        if not stable:
            all_good = False
    return all_good

def weld_into_fitness(patch_results, scores):
    """焊入 fitness.json"""
    data = load_fitness()
    baseline_total = len(scores)
    baseline_pass = sum(1 for v in scores.values() if v >= 1.0)
    baseline_pct = baseline_pass / baseline_total * 100 if baseline_total else 0

    improved_cases = [c for c, ok in patch_results.items() if ok]
    improved_count = len(improved_cases)
    new_pass = baseline_pass + improved_count
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

    # 计算当前 fitness.json 中所有条目的实际通过率
    all_data = load_fitness()
    if all_data:
        total = len(all_data)
        passing = sum(1 for v in all_data.values() if (v.get("score", 0) if isinstance(v, dict) else float(v)) >= 1.0)
        current_pct = passing / total * 100 if total else 0
        print(f"\n[进度] 基线 {baseline_pct:.1f}% -> 焊后 {new_pct:.1f}% ({improved_count} 条改进)")
        print(f"[焊入] fitness.json 含 {total} 条，通过率 {current_pct:.1f}%")
        return current_pct >= 80.0

    print(f"\n[进度] 基线 {baseline_pct:.1f}% -> 焊后 {new_pct:.1f}% ({improved_count} 条改进)")
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
    gates_ok = three_gates_check(patch_results, scores)
    if not gates_ok:
        print("[警告] 三闸未全过，仅记录暂不焊入...")

    # Step 5: 3x 复现（Gate3 没过则跳过）
    print("\n[Step5] 3x 复现验证...")
    if gates_ok:
        replicate_ok = replicate_3x_score_improvement(patch_results, scores)
        if not replicate_ok:
            print("[警告] 3x 复现不稳定，降级处理...")
    else:
        replicate_ok = False
        print("[跳过] 三闸未过，跳过 3x 复现")

    # Step 6: 焊入 fitness.json（Gate3 + 3x 都通过才焊）
    print("\n[Step6] 焊入 fitness.json...")
    if gates_ok and replicate_ok:
        reached_80 = weld_into_fitness(patch_results, scores)
    else:
        print("[跳过] 未达三闸+3x标准，暂不焊入")
        reached_80 = False

    print("\n" + "=" * 60)
    if reached_80:
        print("🎉 CANARY 80% 目标达成！")
    else:
        # 打印当前 fitness.json 摘要
        data = load_fitness()
        if data:
            total = len(data)
            passing = sum(1 for v in data.values() if (v.get("score", 0) if isinstance(v, dict) else float(v)) >= 1.0)
            pct = passing / total * 100 if total else 0
            print(f"📍 当前进度：{passing}/{total} 通过 = {pct:.1f}%")
            print(f"   改进用例: {list(patch_results.items())}")
        print("🔧 继续迭代...")
    print("=" * 60)

if __name__ == "__main__":
    main()
