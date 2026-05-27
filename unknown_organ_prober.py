"""
对仍标"?"的模块跑最小 import/CLI/契约探针，补能力说明，低信任者入退役候选。
通过分析模块源码和实际导入行为来评估未知器官。
"""

import importlib
import inspect
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import ast
import os

def get_unknown_organs() -> List[str]:
    """获取所有标记为"?"的模块（从organ_verification或手动维护）"""
    try:
        from . import organ_verification
        if hasattr(organ_verification, 'get_unknown_organs'):
            return organ_verification.get_unknown_organs()
    except ImportError:
        pass
    
    # 备用方案：从配置文件或直接扫描
    organs_file = Path(__file__).parent / "unknown_organs.txt"
    if organs_file.exists():
        return [line.strip() for line in organs_file.read_text().splitlines() if line.strip()]
    
    # 最后备用：扫描所有.py文件，找出没有能力描述的
    return find_uncharacterized_modules()

def find_uncharacterized_modules() -> List[str]:
    """扫描当前目录，找出没有能力描述的模块"""
    module_dir = Path(__file__).parent
    modules = []
    
    # 尝试从organ_verification获取已知器官列表
    known_organs = set()
    try:
        from . import organ_verification
        if hasattr(organ_verification, 'get_all_organs'):
            known_organs = set(organ_verification.get_all_organs())
    except ImportError:
        pass
    
    for py_file in module_dir.glob("*.py"):
        module_name = py_file.stem
        if module_name.startswith("test_") or module_name.startswith("_"):
            continue
        if module_name not in known_organs and not has_capability_description(py_file):
            modules.append(module_name)
    
    return modules

def has_capability_description(file_path: Path) -> bool:
    """检查文件是否有能力描述（文档字符串或能力清单）"""
    try:
        content = file_path.read_text(encoding='utf-8')
        tree = ast.parse(content)
        
        # 检查模块文档字符串
        if (tree.body and isinstance(tree.body[0], ast.Expr) and 
            isinstance(tree.body[0].value, ast.Str)):
            docstring = tree.body[0].value.s
            if "能力" in docstring or "capability" in docstring.lower():
                return True
        
        # 检查是否有能力清单
        if "CAPABILITY" in content or "能力清单" in content:
            return True
            
    except (SyntaxError, UnicodeDecodeError):
        pass
    
    return False

def probe_module(module_name: str) -> Dict:
    """对单个模块运行最小探针
    
    Returns:
        包含探测结果的字典，包括:
        - module: 模块名
        - import_success: 是否可导入
        - has_cli: 是否有CLI入口
        - has_contracts: 是否有契约
        - trust_score: 信任分数(0-1)
        - capability_description: 能力描述
        - errors: 错误列表
        - functions: 导出的函数列表
        - classes: 导出的类列表
    """
    result = {
        "module": module_name,
        "import_success": False,
        "has_cli": False,
        "has_contracts": False,
        "trust_score": 0.0,
        "capability_description": "",
        "errors": [],
        "functions": [],
        "classes": []
    }
    
    # 1. 尝试导入
    try:
        module = importlib.import_module(f".{module_name}", package="crab")
        result["import_success"] = True
        
        # 2. 检查CLI入口
        result["has_cli"] = has_cli_entry(module)
        
        # 3. 检查契约
        result["has_contracts"] = has_contracts(module)
        
        # 4. 生成能力描述
        result["capability_description"] = generate_capability_description(module)
        
        # 5. 计算信任分数
        result["trust_score"] = calculate_trust_score(module, result)
        
    except Exception as e:
        result["errors"].append(str(e))
    
    return result

def has_cli_entry(module) -> bool:
    """检查模块是否有CLI入口"""
    # 检查 if __name__ == "__main__"
    try:
        source = inspect.getsource(module)
        return 'if __name__ == "__main__"' in source
    except:
        # 备用方案：检查是否有main函数
        return hasattr(module, 'main') and callable(getattr(module, 'main'))

def has_contracts(module) -> bool:
    """检查模块是否实现了契约接口"""
    contract_indicators = [
        "register", "handle", "process", "execute", "validate",
        "CAN_HANDLE", "accepts", "provides", "requires"
    ]
    
    module_attributes = dir(module)
    for indicator in contract_indicators:
        if indicator in module_attributes:
            return True
    
    return False

def generate_capability_description(module) -> str:
    """生成模块能力描述"""
    # 先尝试使用模块的文档字符串
    if module.__doc__:
        doc = module.__doc__.strip()
        if len(doc) < 200:  # 短文档直接用
            return doc
    
    # 分析模块内容生成描述
    capabilities = []
    
    # 检查导出的函数和类
    exported_items = [name for name in dir(module) if not name.startswith('_')]
    if len(exported_items) > 0:
        capabilities.append(f"导出 {len(exported_items)} 个接口")
    
    # 检查是否有特定功能模式
    source = ""
    try:
        source = inspect.getsource(module)
    except:
        pass
    
    if "register" in source:
        capabilities.append("支持注册")
    if "handle" in source:
        capabilities.append("处理事件")
    if "validate" in source:
        capabilities.append("数据验证")
    if "CLI" in source or "argparse" in source:
        capabilities.append("CLI工具")
    
    return "、".join(capabilities) if capabilities else "未知功能"

def calculate_trust_score(module, probe_result: Dict) -> float:
    """计算模块信任分数"""
    score = 0.0
    
    # 导入成功 +0.4
    if probe_result["import_success"]:
        score += 0.4
    
    # 有CLI +0.2
    if probe_result["has_cli"]:
        score += 0.2
    
    # 有契约 +0.2
    if probe_result["has_contracts"]:
        score += 0.2
    
    # 无错误 +0.1
    if not probe_result["errors"]:
        score += 0.1
    
    # 有文档 +0.1
    if module.__doc__ and len(module.__doc__.strip()) > 10:
        score += 0.1
    
    return min(1.0, score)

def run_probe_for_all_unknown():
    """对所有未知器官运行探针"""
    unknown_modules = get_unknown_organs()
    results = []
    
    print(f"发现 {len(unknown_modules)} 个未知器官，开始探测...")
    
    for module_name in unknown_modules:
        print(f"探测: {module_name}")
        result = probe_module(module_name)
        results.append(result)
        
        # 输出简要结果
        status = "✓" if result["import_success"] else "✗"
        trust = f"{result['trust_score']:.2f}"
        print(f"  {status} 信任:{trust} 能力:{result['capability_description'][:50]}")
    
    # 标记低信任者为退役候选
    retirement_candidates = [r["module"] for r in results if r["trust_score"] < 0.3]
    
    if retirement_candidates:
        print(f"\n低信任模块（退役候选）：{retirement_candidates}")
        save_retirement_candidates(retirement_candidates)
    
    return results

def save_retirement_candidates(candidates: List[str]):
    """保存退役候选列表"""
    output_file = Path(__file__).parent / "retirement_candidates.txt"
    with open(output_file, 'w') as f:
        f.write("# 退役候选模块 - 自动生成于 unknown_organ_prober\n")
        f.write(f"# 信任分数低于0.3的模块\n")
        f.write("# 更新时间: " + str(os.path.getmtime(__file__)) + "\n\n")
        for candidate in candidates:
            f.write(f"{candidate}\n")
    
    print(f"退役候选已保存到: {output_file}")

def main():
    """命令行入口"""
    if len(sys.argv) > 1:
        # 探测特定模块
        module_name = sys.argv[1]
        result = probe_module(module_name)
        print(f"模块: {result['module']}")
        print(f"导入: {'成功' if result['import_success'] else '失败'}")
        print(f"CLI: {'有' if result['has_cli'] else '无'}")
        print(f"契约: {'有' if result['has_contracts'] else '无'}")
        print(f"信任: {result['trust_score']:.2f}")
        print(f"能力: {result['capability_description']}")
        if result['errors']:
            print(f"错误: {result['errors']}")
    else:
        # 探测所有未知器官
        run_probe_for_all_unknown()

if __name__ == "__main__":
    main()
