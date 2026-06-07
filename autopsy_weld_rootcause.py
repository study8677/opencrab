"""
autopsy_weld_rootcause.py
========================
三份尸检报告的根因图合一：
  - autopsy_do_canary_75_final.py  (crab方法、fitness.json、do_canary代码bug、canary逻辑)
  - autopsy_real_weld.py            (weld_count未定义、snapshot不存在、reproduce未调用)
  - canary_25pct_dissector.py       (失败用例拆解：真天花板 vs 测量假象)

输出：一张"为什么焊不动"的根因图 + 下刀处建议
"""
import json
import subprocess
import sys
from pathlib import Path
from collections import defaultdict
from typing import Optional

REPO_ROOT = Path(__file__).parent


# ─────────────────────────────────────────────
# 阶段1：crab.py 基础方法审计
# ─────────────────────────────────────────────

def audit_crab_methods() -> dict:
    """检查 crab.py 是否有焊枪需要的核心方法"""
    print("\n" + "=" * 60)
    print("【阶段1-A】crab.py 焊枪方法审计")
    print("=" * 60)

    crab_path = REPO_ROOT / "crab.py"
    if not crab_path.exists():
        return {"ok": False, "reason": "crab.py 不存在"}

    source = crab_path.read_text()

    # 焊枪必备方法
    NEEDED = ["apply_patch", "snapshot", "get_cell", "list_cells"]
    found = {}
    for method in NEEDED:
        found[method] = (
            f"def {method}" in source or f"async def {method}" in source
        )
        status = "✅" if found[method] else "❌"
        print(f"  {status} {method}")

    # 关键方法详情片段
    if "apply_patch" in source:
        idx = source.find("def apply_patch")
        snippet = source[idx:idx+400].split("\n")[0]
        print(f"     片段: {snippet[:80]}")

    all_ok = all(found.values())
    if all_ok:
        print("  → 焊枪ready")
    else:
        print("  → 焊枪哑火：缺少关键方法")

    return {"ok": all_ok, "found": found, "source": source}


# ─────────────────────────────────────────────
# 阶段2：fitness.json 基线审计
# ─────────────────────────────────────────────

def audit_fitness_json() -> dict:
    """检查 fitness.json 是否存在且被回写过"""
    print("\n" + "=" * 60)
    print("【阶段1-B】fitness.json 基线审计")
    print("=" * 60)

    fp = REPO_ROOT / "fitness.json"
    if not fp.exists():
        print("  ❌ fitness.json 不存在")
        print("     → 这就是根因：没有基准分数，无法衡量进步")
        return {"ok": False, "reason": "文件不存在"}

    try:
        with open(fp) as f:
            data = json.load(f)
    except Exception as e:
        print(f"  ❌ 解析失败: {e}")
        return {"ok": False, "reason": f"JSON解析错误: {e}"}

    keys = list(data.keys())
    runs = data.get("runs", [])
    score = data.get("score") or data.get("pass_rate", "N/A")
    delta = data.get("total_delta", "N/A")

    print(f"  ✅ 文件存在")
    print(f"     keys: {keys}")
    print(f"     score/pass_rate: {score}")
    print(f"     runs 条目数: {len(runs)}")
    print(f"     total_delta: {delta}")

    # 判断是否被回写过
    if not runs:
        print("  ⚠️  runs 为空——从未被回写过！")
        return {"ok": False, "reason": "fitness.json 从未被回写，write_fitness_json 可能没执行"}

    return {"ok": True, "data": data, "score": score, "runs": len(runs)}


# ─────────────────────────────────────────────
# 阶段3：canary_75_real_weld.py 焊枪哑火审计
# ─────────────────────────────────────────────

def audit_weld_script() -> dict:
    """检查焊枪脚本本身是否有致命bug"""
    print("\n" + "=" * 60)
    print("【阶段2】canary_75_real_weld.py 焊枪审计")
    print("=" * 60)

    weld_path = REPO_ROOT / "canary_75_real_weld.py"
    if not weld_path.exists():
        print("  ❌ canary_75_real_weld.py 不存在")
        return {"ok": False, "reason": "焊枪脚本不存在"}

    source = weld_path.read_text()
    bugs = []

    # Bug-1: weld_count 未定义
    if "weld_count > 0" in source or "weld_count +" in source:
        # 检查是否在 main() 使用前有定义
        main_start = source.find("def main")
        if main_start < 0:
            main_start = 0
        pre_main = source[:main_start]
        if "weld_count = " not in pre_main:
            bugs.append(("❌ weld_count 未定义",
                         "main() 使用前没有 weld_count = ..."))

    # Bug-2: snapshot() 可能不存在
    if "crab.snapshot()" in source or "trial_crab = crab.snapshot()" in source:
        crab_path = REPO_ROOT / "crab.py"
        if crab_path.exists():
            crab_src = crab_path.read_text()
            if "def snapshot" not in crab_src and "async def snapshot" not in crab_src:
                bugs.append(("❌ snapshot() 不存在",
                             "crab.py 没有 snapshot 方法，crab.snapshot() 会报错"))

    # Bug-3: 3x reproduce 未调用
    if "run_reproduce_verification" in source or "reproduce" in source:
        # 找 main 函数
        main_start = source.find("def main")
        if main_start < 0:
            main_start = source.find("if __name__")
        main_end = source.find("\ndef ", main_start + 1) if main_start >= 0 else -1
        main_body = source[main_start:main_end] if main_end > 0 else source[main_start:]
        if "reproduce" in main_body and "run_reproduce" not in main_body:
            bugs.append(("⚠️ reproduce 逻辑存在但可能没在 main() 中调用",
                         "需要确认 3x 复现验证是否真的执行"))

    # Bug-4: patch 写入后没有 assert 验证
    if "patch" in source.lower() and "assert" not in source.lower():
        bugs.append(("⚠️ patch 写入后没有 assert 验证",
                     "写入后应该 assert patch 真的生效了"))

    if bugs:
        for desc, fix in bugs:
            print(f"  {desc}")
            print(f"     → 修复: {fix}")
    else:
        print("  ✅ 焊枪脚本无明显bug")

    return {"ok": len(bugs) == 0, "bugs": bugs, "source": source}


# ─────────────────────────────────────────────
# 阶段4：do_canary_75_final.py 三闸逻辑审计
# ─────────────────────────────────────────────

def audit_do_canary() -> dict:
    """检查 do_canary_75_final.py 三闸逻辑"""
    print("\n" + "=" * 60)
    print("【阶段3】do_canary_75_final.py 三闸审计")
    print("=" * 60)

    path = REPO_ROOT / "do_canary_75_final.py"
    if not path.exists():
        print("  ❌ do_canary_75_final.py 不存在")
        return {"ok": False, "reason": "文件不存在"}

    source = path.read_text()
    bugs = []

    # 1. astlocator 缺陷是否真的传回主流程
    if "defects_found" in source:
        idx = source.find("defects_found")
        snippet = source[max(0, idx-80):idx+200]
        if "return defects_found" not in snippet and "defects =" not in source[max(0, idx-500):idx]:
            bugs.append(("❌ astlocator 找到的缺陷可能没传回主流程",
                         "defects_found 变量需要 return 或赋值给调用者"))

    # 2. 3x gate 是否有 pass_rate 验证
    step3_start = source.find("def step3")
    step4_start = source.find("def step4")
    if step3_start > 0:
        step3_body = source[step3_start:step4_start] if step4_start > 0 else source[step3_start:step3_start+800]
        if "pass_rate" not in step3_body and "score" not in step3_body and "75" not in step3_body:
            bugs.append(("❌ 3x gate 没有验证分数是否 >= 75%",
                         "gate 必须有 assert pass_rate >= 75 或类似判断"))

    # 3. step5 最终检查是否真的 assert 了分数
    step5_start = source.find("def step5")
    if step5_start > 0:
        step5_body = source[step5_start:step5_start+600]
        if "assert" not in step5_body.lower() and "raise" not in step5_body.lower():
            bugs.append(("❌ step5 没有 assert 验证分数真涨到 75%",
                         "最终检查必须 assert fitness >= 75"))

    # 4. 字符串匹配是否用了硬编码路径
    if "canary.py" in source and ".py" in source:
        # 检查是否有脆弱的字符串匹配
        fragile_patterns = [l for l in source.split('\n') if 'canary.py' in l and '#' not in l]
        if fragile_patterns:
            print(f"  ⚠️ 发现硬编码路径: {fragile_patterns[:3]}")

    if bugs:
        for desc, fix in bugs:
            print(f"  {desc}")
            print(f"     → 修复: {fix}")
    else:
        print("  ✅ 三闸逻辑无明显bug")

    return {"ok": len(bugs) == 0, "bugs": bugs}


# ─────────────────────────────────────────────
# 阶段5：canary.py 健康检查逻辑
# ─────────────────────────────────────────────

def audit_canary_health() -> dict:
    """检查 canary.py 75% 健康检查逻辑"""
    print("\n" + "=" * 60)
    print("【阶段4】canary.py 健康检查审计")
    print("=" * 60)

    path = REPO_ROOT / "canary.py"
    if not path.exists():
        print("  ❌ canary.py 不存在")
        return {"ok": False, "reason": "canary.py 不存在"}

    source = path.read_text()

    # 检查 pass_rate 检查
    has_pass_check = "pass_rate" in source or "score" in source
    print(f"  {'✅' if has_pass_check else '❌'} 存在 pass_rate/score 检查")

    # 检查 75% 阈值
    has_75 = "75" in source
    print(f"  {'✅' if has_75 else '⚠️'} 存在 75% 阈值")

    # 打印健康检查函数
    if "_check_health_score" in source:
        idx = source.find("def _check_health_score")
        end = source.find("\ndef ", idx + 1)
        snippet = source[idx:end] if end > 0 else source[idx:idx+600]
        print(f"\n  _check_health_score 实现片段:\n{snippet[:400]}")
    else:
        print("  ⚠️ 没有 _check_health_score 函数")

    return {"ok": has_pass_check and has_75}


# ─────────────────────────────────────────────
# 阶段6：失败用例拆解（真天花板 vs 测量假象）
# ─────────────────────────────────────────────

def try_dissect_failures() -> dict:
    """尝试运行 canary_25pct_dissector.py 做失败用例拆解"""
    print("\n" + "=" * 60)
    print("【阶段5】失败用例拆解 (canary_25pct_dissector.py)")
    print("=" * 60)

    dissector_path = REPO_ROOT / "canary_25pct_dissector.py"
    if not dissector_path.exists():
        print("  ⚠️ canary_25pct_dissector.py 不存在，跳过")
        return {"skipped": True}

    # 快速运行（只做逻辑检查，不跑3次baseline）
    try:
        # 检查 dissect_failure_case 逻辑是否合理
        source = dissector_path.read_text()

        has_dissect = "def dissect_failure_case" in source
        has_classify = "def classify_failure" in source
        has_artifact = "is_measurement_artifacts" in source or "measurement" in source

        print(f"  {'✅' if has_dissect else '❌'} dissect_failure_case 函数")
        print(f"  {'✅' if has_classify else '❌'} classify_failure 函数")
        print(f"  {'✅' if has_artifact else '❌'} 测量假象检测逻辑")

        return {"ok": True, "has_dissect": has_dissect, "has_classify": has_classify}
    except Exception as e:
        print(f"  ⚠️ 解析失败: {e}")
        return {"skipped": True}


# ─────────────────────────────────────────────
# 阶段7：git 状态快照
# ─────────────────────────────────────────────

def audit_git_status() -> dict:
    """快速检查 git 状态"""
    print("\n" + "=" * 60)
    print("【阶段6】git 状态快照")
    print("=" * 60)

    try:
        result = subprocess.run(
            ["git", "status", "--short"], cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=10
        )
        lines = result.stdout.strip().split('\n')
        if lines and lines[0]:
            print(f"  有 {len(lines)} 个文件变更")
            for l in lines[:5]:
                print(f"    {l}")
        else:
            print("  ✅ 工作区干净")
        return {"dirty": len(lines) > 0 and lines[0] != "", "lines": lines}
    except Exception as e:
        print(f"  ⚠️ git 命令失败: {e}")
        return {"dirty": None, "error": str(e)}


# ─────────────────────────────────────────────
# 汇总：根因图 + 下刀处
# ─────────────────────────────────────────────

def build_rootcause_graph(results: dict) -> str:
    """根据所有诊断结果，构建"为什么焊不动"的根因图"""
    graph = []
    graph.append("""
┌─────────────────────────────────────────────────────────┐
│            为什么 canary 75% 焊不动？根因图              │
└─────────────────────────────────────────────────────────┘
""")

    # 节点A：焊枪基础
    crab_ok = results.get("crab_methods", {}).get("ok", False)
    graph.append(f"[A] 焊枪基础 (crab.py 方法)")
    graph.append(f"    └── apply_patch: {'✅' if results.get('crab_methods', {}).get('found', {}).get('apply_patch') else '❌ 缺失!'}")
    graph.append(f"    └── snapshot:    {'✅' if results.get('crab_methods', {}).get('found', {}).get('snapshot') else '❌ 缺失!'}")
    graph.append(f"    └── get_cell:     {'✅' if results.get('crab_methods', {}).get('found', {}).get('get_cell') else '❌ 缺失!'}")
    graph.append(f"    └── list_cells:   {'✅' if results.get('crab_methods', {}).get('found', {}).get('list_cells') else '❌ 缺失!'}")

    # 节点B：基线
    fitness_ok = results.get("fitness_json", {}).get("ok", False)
    graph.append(f"\n[B] 基线基准 (fitness.json)")
    graph.append(f"    └── 文件存在: {'✅' if fitness_ok else '❌ 不存在!'}")
    if fitness_ok:
        runs = results["fitness_json"].get("runs", 0)
        graph.append(f"    └── runs回写: {'✅' if runs > 0 else '❌ 从未回写!'} ({runs}条)")

    # 节点C：焊枪脚本bug
    weld_ok = results.get("weld_script", {}).get("ok", False)
    bugs = results.get("weld_script", {}).get("bugs", [])
    graph.append(f"\n[C] 焊枪脚本 (canary_75_real_weld.py)")
    graph.append(f"    └── 脚本存在: {'✅' if results.get('weld_script', {}).get('source') else '❌ 不存在!'}")
    if bugs:
        for b in bugs:
            graph.append(f"    └── 🔴 {b[0]} → {b[1]}")
    else:
        graph.append(f"    └── ✅ 无明显bug")

    # 节点D：三闸逻辑
    do_ok = results.get("do_canary", {}).get("ok", False)
    do_bugs = results.get("do_canary", {}).get("bugs", [])
    graph.append(f"\n[D] 三闸逻辑 (do_canary_75_final.py)")
    graph.append(f"    └── 3x gate 验证: {'✅' if do_ok else '❌ 缺失验证!'}")

    # 节点E：canary 健康检查
    canary_ok = results.get("canary_health", {}).get("ok", False)
    graph.append(f"\n[E] 健康检查 (canary.py)")
    graph.append(f"    └── pass_rate 检查: {'✅' if canary_ok else '❌ 缺失!'}")

    # 节点F：失败类型
    dissect = results.get("dissect", {})
    graph.append(f"\n[F] 失败类型 (canary_25pct_dissector.py)")
    if dissect.get("skipped"):
        graph.append(f"    └── ⚠️ 未运行（需要跑3次baseline）")
    else:
        graph.append(f"    └── ✅ 拆解逻辑存在")

    # 根因判决
    graph.append("\n" + "─" * 60)
    graph.append("【根因判决】")
    graph.append("─" * 60)

    rootcauses = []
    if not crab_ok:
        rootcauses.append("🔴 根因A: crab.py 缺少焊枪方法 → 焊枪根本打不响")
    if not fitness_ok:
        rootcauses.append("🔴 根因B: fitness.json 不存在 → 无法衡量进步")
    elif results.get("fitness_json", {}).get("runs", 0) == 0:
        rootcauses.append("🔴 根因B2: fitness.json 从未回写 → write_fitness_json 没执行")
    if not weld_ok:
        rootcauses.append(f"🔴 根因C: 焊枪脚本有bug ({len(bugs)}条)")
    if not do_ok:
        rootcauses.append(f"🔴 根因D: 三闸逻辑缺失验证 ({len(do_bugs)}条)")
    if not canary_ok:
        rootcauses.append("🔴 根因E: canary.py 健康检查不完整")

    if not rootcauses:
        graph.append("⚠️  所有环节都OK，可能是运行时逻辑问题（delta为负/三闸误判）")
        graph.append("    → 建议：跑 canary_25pct_dissector.py 做真/假象判断")
    else:
        for rc in rootcauses:
            graph.append(rc)

    return "\n".join(graph)


def suggest_fixes(results: dict) -> str:
    """根据根因图给出下刀处"""
    suggestions = []
    suggestions.append("\n" + "=" * 60)
    suggestions.append("【下刀处建议】")
    suggestions.append("=" * 60)

    crab_ok = results.get("crab_methods", {}).get("ok", False)
    fitness_ok = results.get("fitness_json", {}).get("ok", False)
    weld_ok = results.get("weld_script", {}).get("ok", False)
    do_ok = results.get("do_canary", {}).get("ok", False)

    priority = 1

    if not crab_ok:
        suggestions.append(f"\n[{priority}] 优先级最高: crab.py 补焊枪方法")
        suggestions.append("    目标: apply_patch, snapshot, get_cell, list_cells")
        suggestions.append("    验证: python -c 'import crab; c=crab.Crab(); print(hasattr(c,\"apply_patch\"))'")
        priority += 1

    if not fitness_ok:
        suggestions.append(f"\n[{priority}] 优先级最高: 建立 fitness.json 基线")
        suggestions.append("    命令: python run_fitness_baseline.py")
        priority += 1

    if not weld_ok:
        bugs = results.get("weld_script", {}).get("bugs", [])
        suggestions.append(f"\n[{priority}] 修复焊枪脚本 (canary_75_real_weld.py)")
        for b in bugs:
            suggestions.append(f"    • {b[1]}")
        priority += 1

    if not do_ok:
        suggestions.append(f"\n[{priority}] 补三闸验证 (do_canary_75_final.py)")
        suggestions.append("    必须: 3x gate 内部 assert pass_rate >= 75")
        suggestions.append("    必须: step5 内部 assert fitness >= 75")
        priority += 1

    if not results.get("canary_health", {}).get("ok"):
        suggestions.append(f"\n[{priority}] 补 canary.py 健康检查")
        suggestions.append("    目标: _check_health_score 必须验 pass_rate >= 75")
        priority += 1

    suggestions.append(f"\n[{priority}] 验证焊枪: python run_canary_75_weld.py")
    suggestions.append(f"[{priority+1}] 验证3x复现: python reproduce_canary_3x.py")

    return "\n".join(suggestions)


# ─────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────

def main():
    print("=" * 60)
    print("CANARY 75% 焊不动 → 根因图生成器")
    print("=" * 60)

    # 顺序执行所有诊断
    results = {}
    results["crab_methods"] = audit_crab_methods()
    results["fitness_json"] = audit_fitness_json()
    results["weld_script"] = audit_weld_script()
    results["do_canary"] = audit_do_canary()
    results["canary_health"] = audit_canary_health()
    results["dissect"] = try_dissect_failures()
    results["git_status"] = audit_git_status()

    # 输出根因图
    print(build_rootcause_graph(results))

    # 输出下刀处
    print(suggest_fixes(results))

    # 保存结构化结果
    save_path = REPO_ROOT / "autopsy_weld_rootcause_result.json"
    serializable = {}
    for k, v in results.items():
        if isinstance(v, dict):
            serializable[k] = {kk: vv for kk, vv in v.items() if not callable(vv) and not kk.startswith('_')}
        else:
            serializable[k] = v

    with open(save_path, "w") as f:
        json.dump(serializable, f, indent=2, default=str)
    print(f"\n✅ 结果已保存: {save_path}")


if __name__ == "__main__":
    main()
