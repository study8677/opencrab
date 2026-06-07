#!/usr/bin/env python3
"""
canary_25pct_audit.py
一次性诊断：25% 失败 case 逐条摊开 + brain-only 修复盲区诊断
"""
import json
import sys
from pathlib import Path
from collections import defaultdict

# ── 路径配置 ──────────────────────────────────────────────────────────────
CRAB_DIR = Path(__file__).parent
FITNESS_JSON = CRAB_DIR / "fitness.json"
MANIFEST_JSON = CRAB_DIR / "manifest.json"
CANARY_RESULTS = CRAB_DIR / "canary_results.json"  # 最新的 canary 执行结果
AUDIT_DIR = CRAB_DIR / "audit_25pct"

AUDIT_DIR.mkdir(exist_ok=True)

# ── 1. 加载数据 ─────────────────────────────────────────────────────────────
def load_json(path, default=None):
    if path.exists():
        return json.loads(path.read_text())
    return default if default is not None else {}

fitness = load_json(FITNESS_JSON, {})
manifest = load_json(MANIFEST_JSON, [])
canary_results = load_json(CANARY_RESULTS, {})

# ── 2. 收集所有 case 状态 ───────────────────────────────────────────────────
# 从 manifest 提取 case 列表（每个 entry 是 dict，id 在 .get("id") 或 .get("case_id")）
cases_by_id = {}
for entry in manifest:
    cid = entry.get("id") or entry.get("case_id") or str(entry)
    cases_by_id[cid] = entry

# 从 fitness.json 提取各 case 的分数
# fitness 结构: {case_id: {"score": float, "passed": bool, ...}}
fitness_scores = {}
for cid, data in fitness.items():
    fitness_scores[cid] = {
        "score": data.get("score", 0.0),
        "passed": data.get("passed", data.get("score", 0) >= 0.7),
        "details": data,
    }

# 从 canary_results 提取
# canary_results 结构: {case_id: {"status": "pass"|"fail"|"brainonly_fail", ...}}
canary_status = canary_results.get("cases", {})

# ── 3. 分类 case ───────────────────────────────────────────────────────────
total_cases = len(cases_by_id)
passed_cases = set()
failed_cases = {}
brainonly_failed = {}
unattempted = {}

for cid, entry in cases_by_id.items():
    fit = fitness_scores.get(cid, {})
    score = fit.get("score", 0.0)
    cr = canary_status.get(cid, {})
    status = cr.get("status", "unknown")
    
    if score >= 0.7 or cr.get("patch_applied"):
        passed_cases.add(cid)
    elif status in ("fail", "error", "timeout") or score < 0.7:
        # 收集失败信息
        fail_reason = cr.get("fail_reason") or fit.get("details", {}).get("error", "unknown")
        if "brainonly" in str(fail_reason).lower() or cr.get("brainonly_attempted"):
            brainonly_failed[cid] = {
                "entry": entry,
                "fitness_score": score,
                "canary_status": status,
                "fail_reason": fail_reason,
                "patch_attempted": cr.get("brainonly_patch"),
                "error_trace": cr.get("traceback", "")[:500],
            }
        else:
            failed_cases[cid] = {
                "entry": entry,
                "fitness_score": score,
                "canary_status": status,
                "fail_reason": fail_reason,
                "error_trace": cr.get("traceback", "")[:500],
            }
    else:
        unattempted[cid] = entry

# ── 4. 输出摘要 ─────────────────────────────────────────────────────────────
print("=" * 70)
print("CANARY 25% 失败 CASE 逐条摊开审计")
print("=" * 70)
print(f"\n📊 总 case 数: {total_cases}")
print(f"✅ 通过: {len(passed_cases)} ({100*len(passed_cases)/max(total_cases,1):.1f}%)")
print(f"❌ 失败 (普通): {len(failed_cases)}")
print(f"🧠 brain-only 修不动: {len(brainonly_failed)}")
print(f"⏳ 未尝试: {len(unattempted)}")

# ── 5. 逐条分析失败 case ───────────────────────────────────────────────────
print("\n" + "=" * 70)
print("【逐条分析】普通失败 CASE (非 brain-only)")
print("=" * 70)

for i, (cid, info) in enumerate(sorted(failed_cases.items()), 1):
    print(f"\n── Case #{i}: {cid} ──")
    print(f"  Fitness 分数: {info['fitness_score']:.3f}")
    print(f"  Canary 状态: {info['canary_status']}")
    print(f"  失败原因: {info['fail_reason']}")
    trace = info['error_trace']
    if trace:
        print(f"  错误迹(前500字符):\n    {trace[:500].replace(chr(10), chr(10)+'    ')}")
    # 提取关键诊断点
    entry = info['entry']
    tags = entry.get("tags", []) if isinstance(entry, dict) else []
    module = entry.get("module", "unknown") if isinstance(entry, dict) else "unknown"
    print(f"  标签: {tags}, 模块: {module}")

# ── 6. 逐条分析 brain-only 失败 ─────────────────────────────────────────────
print("\n" + "=" * 70)
print("【逐条分析】BRAIN-ONLY 修不动的 CASE")
print("=" * 70)

# 分类 brain-only 失败原因
BO_CATEGORIES = {
    "判定太严": [],      # patch 实际上有效但判定逻辑拒绝
    "测试脆性": [],      # 测试本身不稳定/随机性
    "代码盲区": [],      # 修复触及不到的地方(外部依赖/系统差异)
    "未知": [],
}

for i, (cid, info) in enumerate(sorted(brainonly_failed.items()), 1):
    print(f"\n── Brain-Only Case #{i}: {cid} ──")
    print(f"  Fitness 分数: {info['fitness_score']:.3f}")
    print(f"  Canary 状态: {info['canary_status']}")
    print(f"  失败原因: {info['fail_reason']}")
    trace = info['error_trace']
    if trace:
        print(f"  错误迹:\n    {trace[:600].replace(chr(10), chr(10)+'    ')}")
    
    # 深度诊断
    entry = info['entry']
    tags = entry.get("tags", []) if isinstance(entry, dict) else []
    module = entry.get("module", "unknown") if isinstance(entry, dict) else "unknown"
    
    # 分析失败类型
    fail_lower = str(info['fail_reason']).lower()
    trace_lower = str(trace).lower()
    
    if any(k in fail_lower or k in trace_lower for k in ["assertion", "assert", "test failed", "expected"]):
        category = "测试脆性"
    elif any(k in fail_lower or k in trace_lower for k in ["timeout", "hang", "deadlock"]):
        category = "代码盲区"
    elif any(k in fail_lower or k in trace_lower for k in ["import", "module", "dependency", "not found"]):
        category = "代码盲区"
    elif any(k in fail_lower or k in trace_lower for k in ["score", "threshold", "reject", "below"]):
        category = "判定太严"
    else:
        category = "未知"
    
    print(f"  诊断归类: 【{category}】")
    print(f"  标签: {tags}, 模块: {module}")
    BO_CATEGORIES[category].append(cid)

# ── 7. 输出归类汇总 ────────────────────────────────────────────────────────
print("\n" + "=" * 70)
print("【BRAIN-ONLY 失败归类汇总】")
print("=" * 70)
for cat, cids in BO_CATEGORIES.items():
    if cids:
        print(f"\n  {cat}: {len(cids)} 个")
        for c in cids:
            print(f"    - {c}")

# ── 8. 写入详细报告 ────────────────────────────────────────────────────────
report = {
    "summary": {
        "total": total_cases,
        "passed": len(passed_cases),
        "failed_normal": len(failed_cases),
        "failed_brainonly": len(brainonly_failed),
        "unattempted": len(unattempted),
    },
    "failed_cases": {cid: {k: str(v) for k, v in info.items()} for cid, info in failed_cases.items()},
    "brainonly_failed": {cid: {k: str(v) for k, v in info.items()} for cid, info in brainonly_failed.items()},
    "brainonly_categories": {cat: list(cids) for cat, cids in BO_CATEGORIES.items()},
}

report_path = AUDIT_DIR / "canary_25pct_report.json"
report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False))
print(f"\n📄 详细报告已写入: {report_path}")

# ── 9. 如果有 test_brainonly_*.py 的历史记录，也一并分析 ──────────────────
print("\n" + "=" * 70)
print("【历史回查】brainonly_*.py 修复记录")
print("=" * 70)

brainonly_scripts = list(CRAB_DIR.glob("brainonly_*.py"))
for script in sorted(brainonly_scripts):
    content = script.read_text()
    # 提取 patch 内容或失败原因
    lines = content.split("\n")
    print(f"\n  📝 {script.name}")
    # 打印前 20 行摘要
    for line in lines[:20]:
        if any(k in line.lower() for k in ["case", "fail", "patch", "fix", "reason"]):
            print(f"    {line[:100]}")

print("\n" + "=" * 70)
print("✅ 审计完成。核心问题已定位在 brainonly_categories 中。")
print("=" * 70)
