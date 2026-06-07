"""
autopsy_canary_75_25pct_rootcause.py
对 canary 75% 那 25% 失败用例做根因分类：
  Type-A: 外部依赖缺失（网络/服务/真实模型/真值）
  Type-B: brain-only 触不到的深层逻辑（AST 解析边界、多模块协作副作用、非确定性）
  Type-C: 复现抖动（偶发、非稳定失败）
  Type-D: 待定/需进一步诊断
"""

import json
import os
import sys
from pathlib import Path

# 尝试找到 canary_75 的执行记录
CANDIDATE_PATHS = [
    Path("results/canary_75_run.jsonl"),
    Path("canary_75_results.jsonl"),
    Path("logs/canary_75_autopsy.jsonl"),
    Path("autopsy_canary_75_results.json"),
    Path("autopsy_canary_75_final.json"),
]

def load_results():
    for p in CANDIDATE_PATHS:
        if p.exists():
            print(f"Found: {p}")
            if p.suffix == ".jsonl":
                records = []
                with open(p) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            records.append(json.loads(line))
                return records
            elif p.suffix == ".json":
                with open(p) as f:
                    return json.load(f)
    return None

def classify_failure(record):
    """根据 record 内容判断根因类型"""
    # 尝试多个可能字段
    reason = (
        record.get("failure_reason")
        or record.get("reason")
        or record.get("error")
        or record.get("root_cause")
        or record.get("diagnosis")
        or ""
    )
    tool_calls = record.get("tool_calls", [])
    error_msg = record.get("error_message", "")

    combined = f"{reason} {error_msg}".lower()

    # Type-A: 外部依赖
    type_a_signals = [
        "network", "connection", "timeout", "http", "api",
        "real model", "真实模型", "external", "外部",
        "dependency", "service unavailable", "no such file",
        "permission denied", "file not found", "import",
        "module", "openai", "anthropic", "rate limit",
        "ssl", "certificate",
    ]

    # Type-B: 深层逻辑
    type_b_signals = [
        "ast", "parse", "syntax", "semantic", "logic",
        "multi-module", "side effect", "副作用",
        "nondeterministic", "race condition", "timing",
        "import order", "module interaction",
        "complexity", "overfit", "over-fitting",
    ]

    # Type-C: 复现抖动
    type_c_signals = [
        "flaky", "intermittent", "sometimes", "occasionally",
        "unstable", "jitter", "noise",
    ]

    for sig in type_a_signals:
        if sig in combined:
            return "Type-A: External Dependency"

    for sig in type_b_signals:
        if sig in combined:
            return "Type-B: Deep Logic (brain-only blind)"

    for sig in type_c_signals:
        if sig in combined:
            return "Type-C: Flaky/Reproducibility"

    return "Type-D: Unknown (needs more diagnosis)"

def audit_canary_75_25pct():
    records = load_results()
    if not records:
        print("No existing results found. Checking for partial data...")
        # 尝试从多个 autopsy 文件汇总
        all_records = []
        for autopsy_file in Path(".").glob("*autopsy*canary*75*.py"):
            pass  # skip source files
        for json_file in Path(".").glob("*.json"):
            if "canary" in json_file.name.lower() and "75" in json_file.name:
                try:
                    with open(json_file) as f:
                        data = json.load(f)
                        if isinstance(data, list):
                            all_records.extend(data)
                        elif isinstance(data, dict):
                            all_records.append(data)
                except Exception:
                    pass
        if all_records:
            records = all_records
            print(f"Found {len(records)} records across JSON files")

    if not records:
        print("ERROR: No canary_75 execution records found.")
        print("Need to run canary_75 first to generate failure data.")
        print("\nSuggestion: Run one of these first:")
        print("  python run_canary_75_final.py")
        print("  python execute_canary_75.py")
        print("  python do_canary_75_final.py")
        return

    print(f"\n=== Canary 75% 25% Failure Autopsy ===")
    print(f"Total records loaded: {len(records)}")

    # 分析成功 vs 失败
    passed = []
    failed = []

    for r in records:
        status = r.get("status") or r.get("result") or r.get("passed")
        if isinstance(status, bool):
            if status:
                passed.append(r)
            else:
                failed.append(r)
        elif isinstance(status, str):
            if status.lower() in ("pass", "success", "passed", "true"):
                passed.append(r)
            else:
                failed.append(r)
        else:
            # 尝试用其他方式判断
            if r.get("score", 0) >= 0.75:
                passed.append(r)
            else:
                failed.append(r)

    total = len(records)
    pass_rate = len(passed) / total * 100 if total > 0 else 0

    print(f"\nPass: {len(passed)} ({pass_rate:.1f}%)")
    print(f"Fail: {len(failed)} ({100-pass_rate:.1f}%)")
    print(f"Target was 75%, so analyzing the {len(failed)} failure cases:\n")

    # 分类失败
    type_counts = {}
    type_examples = {}

    for r in failed:
        classification = classify_failure(r)
        type_counts[classification] = type_counts.get(classification, 0) + 1

        if classification not in type_examples:
            type_examples[classification] = []
        if len(type_examples[classification]) < 3:
            type_examples[classification].append({
                "case": r.get("case_id") or r.get("id") or r.get("task_id", "unknown"),
                "reason": r.get("failure_reason") or r.get("reason") or r.get("error", "")[:100],
            })

    print("=" * 70)
    print("FAILURE ROOT CAUSE DISTRIBUTION")
    print("=" * 70)

    for classification, count in sorted(type_counts.items(), key=lambda x: -x[1]):
        pct = count / len(failed) * 100 if len(failed) > 0 else 0
        print(f"\n{classification}: {count} cases ({pct:.1f}% of failures)")
        print("-" * 50)
        for ex in type_examples.get(classification, []):
            print(f"  Case {ex['case']}: {ex['reason']}")

    print("\n" + "=" * 70)
    print("STRATEGIC RECOMMENDATION")
    print("=" * 70)

    type_a = type_counts.get("Type-A: External Dependency", 0)
    type_b = type_counts.get("Type-B: Deep Logic (brain-only blind)", 0)
    type_c = type_counts.get("Type-C: Flaky/Reproducibility", 0)
    type_d = type_counts.get("Type-D: Unknown (needs more diagnosis)", 0)

    if type_b + type_d == len(failed):
        print("\n>>> VERDICT: Most/all failures are Type-B (brain-only blind spots)")
        print(">>> ACTION: Focus on boundaryeval / arena with softer targets")
        print(">>> AVOID: Spending more cycles on canary_75 direct improvement")
    elif type_a > 0:
        print(f"\n>>> VERDICT: {type_a} cases are external dependency issues")
        print(">>> ACTION: These cannot be fixed by brain-only. Consider mocking or skipping.")
    elif type_c > 0:
        print(f"\n>>> VERDICT: {type_c} cases are flaky/intermittent")
        print(">>> ACTION: Stabilize reproducibility before targeting 80%.")
    else:
        print("\n>>> VERDICT: Mixed or unknown. Need more data.")
        print(">>> ACTION: Run canary_75 again to collect failure evidence.")

    # 保存分类结果
    output = {
        "total": total,
        "passed": len(passed),
        "failed": len(failed),
        "pass_rate": pass_rate,
        "classification": {k: v for k, v in type_counts.items()},
        "examples": type_examples,
        "verdict": "pending" if type_b + type_d == len(failed) else "mixed",
    }

    with open("canary_75_25pct_rootcause.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nResults saved to: canary_75_25pct_rootcause.json")
    return output

if __name__ == "__main__":
    audit_canary_75_25pct()
