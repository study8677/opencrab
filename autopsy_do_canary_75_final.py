"""
尸检报告：do_canary_75_final.py 为何没让 canary 涨过 75%
"""
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def audit_crab_methods():
    """1. 检查 crab.py 是否有 apply_patch"""
    print("=" * 60)
    print("【1】crab.py apply_patch 审计")
    print("=" * 60)

    crab_path = REPO_ROOT / "crab.py"
    if not crab_path.exists():
        print("❌ crab.py 不存在！")
        return False

    source = crab_path.read_text()

    methods_needed = ["apply_patch", "snapshot", "get_cell", "list_cells"]

    all_found = True
    for method in methods_needed:
        found = f"def {method}" in source or f"async def {method}" in source
        status = "✅" if found else "❌"
        print(f"  {status} {method}: {'存在' if found else '不存在！'}")
        if not found:
            all_found = False

    if "apply_patch" in source:
        idx = source.find("def apply_patch")
        snippet = source[idx:idx+500] if idx >= 0 else ""
        print(f"\n  apply_patch 实现片段:\n{snippet[:500]}")

    return all_found

def audit_fitness_json():
    """2. 检查 fitness.json"""
    print("\n" + "=" * 60)
    print("【2】fitness.json 审计")
    print("=" * 60)

    fp = REPO_ROOT / "fitness.json"
    if not fp.exists():
        print("❌ fitness.json 不存在！")
        print("   → 这就是根因：没有基准分数，无法衡量进步")
        return False

    try:
        with open(fp) as f:
            data = json.load(f)
        print(f"✅ fitness.json 存在")
        print(f"   keys: {list(data.keys())}")
        score = data.get("score") or data.get("pass_rate", "N/A")
        print(f"   score/pass_rate: {score}")
        print(f"   runs 条目数: {len(data.get('runs', []))}")
        print(f"   total_delta: {data.get('total_delta', 'N/A')}")
        return True
    except Exception as e:
        print(f"❌ 解析失败: {e}")
        return False

def audit_do_canary_code():
    """3. 检查 do_canary_75_final.py 本身的 bug"""
    print("\n" + "=" * 60)
    print("【3】do_canary_75_final.py 代码审计")
    print("=" * 60)

    path = REPO_ROOT / "do_canary_75_final.py"
    if not path.exists():
        print("❌ do_canary_75_final.py 不存在！")
        return False

    source = path.read_text()
    bugs = []

    # Bug 1: astlocator 返回什么？step1 依赖的缺陷检测逻辑是否有效
    if "astlocator" in source and "defect" in source:
        # 检查是否真的用了 astlocator 结果
        if "defects_found" in source:
            idx = source.find("defects_found")
            snippet = source[max(0, idx-100):idx+200]
            if "return defects_found" not in snippet:
                bugs.append(("⚠️ 缺陷: astlocator 找到的缺陷可能没返回到主流程"))

    # Bug 2: step2 的字符串匹配太脆弱
    if "len(list(evidence_dir.iterdir())) >= 0" in source:
        canary_src = (REPO_ROOT / "canary.py").read_text()
        if "len(list(evidence_dir.iterdir())) >= 0" not in canary_src:
            bugs.append(("❌ step2 修补目标在 canary.py 中不存在",
                        "实际代码可能用了不同的写法"))

    # Bug 3: 健康检查是否真的在验 75%？
    if "_check_health_score" in source:
        health_check = source[source.find("def _check_health_score"):source.find("def _check_health_score")+400]
        print(f"\n  健康检查片段:\n{health_check[:400]}")
        # 检查是否验了 75
        if "75" not in health_check and "pass_rate" not in health_check:
            bugs.append(("❌ 根因: _check_health_score 没有验证 pass_rate >= 75%"))

    # Bug 4: 3x gate 是否真的验了分数增长
    step3 = source[source.find("def step3_three_gates"):source.find("def step4_git_commit")]
    print(f"\n  3x gate 片段:\n{step3[:600]}")
    if "pass_rate" not in step3 and "score" not in step3 and "75" not in step3:
        bugs.append(("❌ 根因: 3x gate 没有验证分数是否 >= 75%"))

    # Bug 5: 最终检查是否确认了分数增长
    step5 = source[source.find("def step5_rerun_check_fitness"):]
    print(f"\n  step5 片段:\n{step5[:600]}")
    if "assert" not in step5.lower() and "raise" not in step5.lower() and ">= 75" not in step5:
        bugs.append(("⚠️ 根因: step5 没有 assert 验证分数真涨了 75"))

    if bugs:
        for desc, fix in bugs:
            print(f"\n  {desc}")
            print(f"     → 修复建议: {fix}")
        return False
    else:
        print("  ✅ 未发现明显 bug")
        return True

def audit_canary_75_logic():
    """4. 检查 canary.py 的 75% 逻辑"""
    print("\n" + "=" * 60)
    print("【4】canary.py 75% 逻辑审计")
    print("=" * 60)

    path = REPO_ROOT / "canary.py"
    if not path.exists():
        print("❌ canary.py 不存在！")
        return False

    source = path.read_text()

    # 检查 pass_rate 检查
    if "pass_rate" in source or "score" in source:
        print("  ✅ 存在 pass_rate/score 检查")
    else:
        print("  ❌ canary.py 没有 pass_rate/score 检查")

    # 检查 75% 阈值
    if "75" in source:
        print("  ✅ 存在 75% 阈值")
    else:
        print("  ⚠️ 未硬编码 75% 阈值")

    # 打印健康检查函数
    if "_check_health_score" in source:
        idx = source.find("def _check_health_score")
        end = source.find("\ndef ", idx + 1)
        snippet = source[idx:end] if end > 0 else source[idx:idx+600]
        print(f"\n  _check_health_score 实现:\n{snippet[:600]}")

def audit_git_log():
    """5. 检查 git log 看历史"""
    print("\n" + "=" * 60)
    print("【5】git log 最近 commits")
    print("=" * 60)

    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=10
        )
        print(result.stdout)
    except Exception as e:
        print(f"⚠️ git log 失败: {e}")

def main():
    print("🔍 CANARY 75% 焊死失败根因诊断")
    print("=" * 60)

    results = {
        "crab_methods": audit_crab_methods(),
        "fitness_json": audit_fitness_json(),
        "do_canary_code": audit_do_canary_code(),
        "canary_75_logic": audit_canary_75_logic(),
    }

    audit_git_log()

    print("\n" + "=" * 60)
    print("【结论】")
    print("=" * 60)

    if not results["crab_methods"]:
        print("❌ 根因: crab.py 缺少关键方法")
    elif not results["do_canary_code"]:
        print("❌ 根因: do_canary_75_final.py 本身有致命 bug")
    elif not results["fitness_json"]:
        print("❌ 根因: 没有 baseline 基准，跑也白跑")
    else:
        print("✅ 代码链条完整，问题可能在运行时逻辑")

    print("\n【下一步行动】")
    print("1. 如果 fitness.json 不存在 → 先运行 baseline 建立基准")
    print("2. 如果代码有 bug → 修复 do_canary_75_final.py")
    print("3. 如果逻辑缺失 → 补上 pass_rate >= 75 的 assert")

if __name__ == "__main__":
    main()
