"""
canary 25% 失败用例诊断器
目标：把失败拆到函数/输入级，判断「真天花板」还是「测量/定位假象」
"""
import json
import sys
import subprocess
from pathlib import Path
from collections import defaultdict

# 核心拆解维度
DISSECT_LEVELS = ["function", "input", "module", "patchsite"]

def run_baseline_once():
    """运行一次 4-grid baseline，返回原始结果"""
    result = subprocess.run(
        ["python", "run_4grid_mini_baseline.py"],
        capture_output=True,
        text=True,
        timeout=300
    )
    # 假设输出 JSON 格式的结果
    try:
        output = result.stdout.strip().split('\n')[-1]
        return json.loads(output)
    except:
        return {"error": result.stdout + result.stderr}

def dissect_failure_case(case_id, baseline_result):
    """将单个失败用例拆解到函数/输入级"""
    # 提取失败上下文
    context = {
        "case_id": case_id,
        "module": baseline_result.get("module", "unknown"),
        "function": baseline_result.get("function", "unknown"),
        "input_hash": hash(str(baseline_result.get("input", ""))),
        "patchsite": baseline_result.get("patchsite", "unknown"),
        "failure_type": classify_failure(baseline_result),
    }
    return context

def classify_failure(result):
    """分类失败类型"""
    error = result.get("error", "")
    fitness = result.get("fitness", 0)
    
    if "SyntaxError" in error or "IndentationError" in error:
        return "syntax_error"
    elif "ImportError" in error or "ModuleNotFoundError" in error:
        return "import_error"
    elif fitness == 0:
        return "zero_fitness"
    elif fitness < 0.5:
        return "low_fitness"
    else:
        return "edge_case"

def is_measurement_artifacts(dissected_cases):
    """判断是否为测量/定位假象"""
    # 假象特征：同一函数反复失败 + 输入高度相似
    by_function = defaultdict(list)
    for case in dissected_cases:
        by_function[case["function"]].append(case)
    
    symptoms = {
        "same_function_repeated": 0,
        "similar_inputs": 0,
        "consistent_failure_point": True
    }
    
    for func, cases in by_function.items():
        if len(cases) > 1:
            symptoms["same_function_repeated"] += 1
            # 检查输入相似度
            inputs = [c["input_hash"] for c in cases]
            if len(set(inputs)) < len(inputs) * 0.3:
                symptoms["similar_inputs"] += 1
    
    # 真天花板的特征：随机分布 + 多种失败类型
    unique_functions = len(by_function)
    failure_types = set(c["failure_type"] for c in dissected_cases)
    
    is_artifact = (
        symptoms["same_function_repeated"] > len(dissected_cases) * 0.5 or
        symptoms["similar_inputs"] > 0
    )
    
    return is_artifact, {
        "symptoms": symptoms,
        "unique_functions": unique_functions,
        "failure_types": list(failure_types),
    }

def main():
    print("=" * 60)
    print("CANARY 25% 失败用例诊断")
    print("=" * 60)
    
    # 收集 3 次 baseline 结果以提高置信度
    all_results = []
    for i in range(3):
        print(f"\n>>> 运行 baseline #{i+1}/3")
        result = run_baseline_once()
        all_results.append(result)
    
    # 提取失败用例
    failures = []
    for run_idx, result in enumerate(all_results):
        if result.get("canary_triggered") or result.get("fitness", 1) < 0.75:
            failures.append({
                "run": run_idx,
                **result
            })
    
    print(f"\n>>> 收集到 {len(failures)} 个失败用例")
    
    # 拆解到函数/输入级
    dissected = [dissect_failure_case(f["run"], f) for f in failures]
    
    print("\n>>> 拆解结果:")
    for d in dissected:
        print(f"  [{d['failure_type']}] {d['function']} @ {d['patchsite']}")
    
    # 判断是真天花板还是假象
    is_artifact, evidence = is_measurement_artifacts(dissected)
    
    print("\n" + "=" * 60)
    print("诊断结论")
    print("=" * 60)
    
    if is_artifact:
        print("❌ 测量/定位假象 - 需要重做 astlocator")
        print(f"   证据: {evidence}")
        print("   建议: 修复定位逻辑后再测")
    else:
        print("⚠️  真天花板 - 75% 是当前算法极限")
        print(f"   证据: {evidence}")
        print("   建议: 转攻 boundaryeval")
    
    return is_artifact, evidence

if __name__ == "__main__":
    is_artifact, evidence = main()
    sys.exit(0 if is_artifact else 1)
