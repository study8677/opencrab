"""
影响面驱动的最小验证选择器：根据代码改动自动推荐必跑的验证命令。
串起 impact→regression→evidence 三要素，为每次小改推荐最小但必要的验证集。
"""
from typing import List, Set, Optional, Tuple, Dict, Any
import os
import importlib
from pathlib import Path


def get_changed_files(changes_dir: Optional[str] = None) -> List[str]:
    """获取最近改动的文件列表，可以从指定目录扫描或通过其他方式获取。"""
    if changes_dir and os.path.exists(changes_dir):
        # 从指定目录获取改动文件
        return [f for f in os.listdir(changes_dir) if f.endswith('.py')]
    # 否则返回一个示例列表用于演示
    return ["crab.py", "minimal_verify_selector.py"]


def get_impacted_areas(changed_files: List[str]) -> Set[str]:
    """分析改动文件的影响面，返回受影响的区域/模块集合。"""
    impacted = set()
    # 分析每个改动文件，识别影响面
    for file in changed_files:
        # 简单映射：文件名 -> 影响区域
        if "crab.py" in file:
            impacted.update(["core", "commands", "lifecycle"])
        elif "impact.py" in file:
            impacted.update(["analysis", "impact"])
        elif "regression.py" in file:
            impacted.update(["testing", "regression"])
        elif "evidence.py" in file:
            impacted.update(["analysis", "evidence"])
        elif "test_" in file or "_test.py" in file:
            impacted.add("testing")
        else:
            # 通用映射
            module_name = Path(file).stem
            impacted.add(module_name)
    return impacted


def get_regression_tests(impacted_areas: Set[str]) -> Set[str]:
    """根据影响面获取对应的回归测试命令集合。"""
    test_mapping = {
        "core": ["python -m pytest tests/test_core.py -v", "python -m crab compatibility-check"],
        "commands": ["python -m pytest tests/test_commands.py -v"],
        "lifecycle": ["python -m crab lifecycle-check", "python -m pytest tests/test_lifecycle.py -v"],
        "analysis": ["python -m pytest tests/test_analysis.py -v"],
        "impact": ["python -m crab impact-check --verbose"],
        "testing": ["python -m pytest tests/ -v", "python -m crab regression-run"],
        "regression": ["python -m crab regression-run --target=regression.py", "python -m pytest tests/test_regression.py -v"],
        "evidence": ["python -m crab evidence-check --freshness", "python -m pytest tests/test_evidence.py -v"],
    }
    
    tests = set()
    for area in impacted_areas:
        if area in test_mapping:
            tests.update(test_mapping[area])
    return tests


def get_evidence_requirements(impacted_areas: Set[str]) -> Set[str]:
    """根据影响面获取证据要求/必须运行的验证命令。"""
    evidence_mapping = {
        "core": ["python -m crab verify-core-integrity"],
        "commands": ["python -m crab verify-command-syntax"],
        "lifecycle": ["python -m crab verify-lifecycle-transitions"],
        "analysis": ["python -m crab verify-analysis-pipeline"],
        "impact": ["python -m crab verify-impact-calculation"],
        "regression": ["python -m crab verify-regression-baseline"],
        "evidence": ["python -m crab verify-evidence-chain"],
    }
    
    evidence = set()
    for area in impacted_areas:
        if area in evidence_mapping:
            evidence.update(evidence_mapping[area])
    return evidence


def minimize_command_set(regression: Set[str], evidence: Set[str]) -> Set[str]:
    """最小化命令集合：去重、去冲突、选择最小必要集。"""
    # 合并所有命令
    all_commands = regression | evidence
    
    # 简单去重和优先级处理
    # 这里可以根据实际逻辑进一步优化
    minimal = set()
    for cmd in all_commands:
        # 跳过重复的或更低优先级的
        if "pytest" in cmd and "crab" in cmd:
            # pytest 通常比 crab 命令更通用
            if "python -m pytest tests/ -v" in minimal:
                continue
        minimal.add(cmd)
    
    return minimal


def recommend_minimal_verification(changed_files: Optional[List[str]] = None) -> Dict[str, Any]:
    """
    主函数：根据代码改动推荐最小验证集。
    
    返回：
        dict: 包含以下字段：
            - changed_files: 改动的文件列表
            - impacted_areas: 影响面集合
            - regression_tests: 回归测试命令
            - evidence_requirements: 证据要求命令
            - recommended_commands: 推荐的最小命令集合
            - rationale: 推荐理由
    """
    if changed_files is None:
        changed_files = get_changed_files()
    
    # 步骤1：分析影响面
    impacted = get_impacted_areas(changed_files)
    
    # 步骤2：获取回归测试
    regression = get_regression_tests(impacted)
    
    # 步骤3：获取证据要求
    evidence = get_evidence_requirements(impacted)
    
    # 步骤4：最小化命令集
    minimal_commands = minimize_command_set(regression, evidence)
    
    # 生成推荐理由
    rationale = f"基于{len(changed_files)}个文件的改动，影响了{len(impacted)}个区域。"
    rationale += f"从{len(regression)}个回归测试和{len(evidence)}个证据要求中选择了{len(minimal_commands)}个最小必要命令。"
    
    if "core" in impacted:
        rationale += " 注意：核心模块改动，必须验证完整性。"
    if "regression" in impacted:
        rationale += " 注意：回归模块改动，必须验证基线。"
    
    return {
        "changed_files": changed_files,
        "impacted_areas": impacted,
        "regression_tests": regression,
        "evidence_requirements": evidence,
        "recommended_commands": minimal_commands,
        "rationale": rationale
    }


# CLI 入口
def main():
    """命令行接口，可直接运行此模块。"""
    import argparse
    parser = argparse.ArgumentParser(description="影响面驱动的最小验证选择器")
    parser.add_argument("--files", nargs="*", help="要分析的文件列表")
    parser.add_argument("--changes-dir", help="包含改动文件的目录")
    args = parser.parse_args()
    
    if args.files:
        changed_files = args.files
    else:
        changed_files = get_changed_files(args.changes_dir)
    
    result = recommend_minimal_verification(changed_files)
    
    print("=" * 60)
    print("影响面驱动的最小验证选择器")
    print("=" * 60)
    print(f"改动文件: {result['changed_files']}")
    print(f"影响面: {result['impacted_areas']}")
    print(f"回归测试候选: {len(result['regression_tests'])}")
    print(f"证据要求候选: {len(result['evidence_requirements'])}")
    print("-" * 60)
    print("推荐的最小验证命令:")
    for i, cmd in enumerate(sorted(result['recommended_commands']), 1):
        print(f"  {i}. {cmd}")
    print("-" * 60)
    print(f"理由: {result['rationale']}")
    print("=" * 60)
    
    return result


if __name__ == "__main__":
    main()
