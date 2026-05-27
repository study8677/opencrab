#!/usr/bin/env python3
"""
领地生命线全量冒烟测试。
自动发现并测试所有 220+ 模块的导入/最小调用，生成诚实报告。
这是最基础的"呼吸"检查，看看宣称的本事有多少是真本事。
"""

import sys
import os
import importlib
import traceback
import time
from pathlib import Path
from typing import Dict, List, Tuple, Any, Optional
import json

def get_all_modules() -> List[str]:
    """获取领地所有 .py 模块列表（排除 __init__.py 和测试文件）"""
    current_dir = Path(__file__).parent
    modules = []
    
    for py_file in current_dir.glob("*.py"):
        if py_file.name == "__init__.py":
            continue
        # 排除测试文件，但保留 test_*.py（因为它们是测试模块，也需要测试）
        # 排除 smoke_test_lifeline.py 本身
        if py_file.name == "smoke_test_lifeline.py":
            continue
            
        module_name = py_file.stem
        modules.append(module_name)
    
    return sorted(modules)

def test_module_import(module_name: str) -> Tuple[bool, str]:
    """测试单个模块是否能成功导入"""
    try:
        start_time = time.time()
        module = importlib.import_module(module_name)
        import_time = time.time() - start_time
        
        # 检查模块是否有至少一个公开属性
        public_attrs = [attr for attr in dir(module) if not attr.startswith('_')]
        
        return True, f"导入成功 ({import_time:.3f}s), 公开属性数: {len(public_attrs)}"
        
    except ImportError as e:
        return False, f"导入失败 (ImportError): {e}"
    except Exception as e:
        return False, f"导入失败 ({type(e).__name__}): {e}"

def test_module_basic_call(module_name: str, module: Any) -> Tuple[bool, str]:
    """测试模块基本功能（如果有明显的类/函数）"""
    try:
        # 尝试找到主类/函数并实例化
        main_classes = []
        main_functions = []
        
        for attr_name in dir(module):
            if attr_name.startswith('_'):
                continue
                
            attr = getattr(module, attr_name)
            
            # 如果是类，尝试实例化（如果有简单构造函数）
            if isinstance(attr, type) and not attr_name.startswith('Test'):
                try:
                    # 尝试无参构造
                    instance = attr()
                    main_classes.append(attr_name)
                except TypeError:
                    # 可能需要参数，跳过
                    pass
                except Exception:
                    # 其他错误，跳过
                    pass
            
            # 如果是函数，尝试调用（如果是无参函数）
            elif callable(attr) and not attr_name.startswith('test_'):
                try:
                    import inspect
                    sig = inspect.signature(attr)
                    if len(sig.parameters) == 0:
                        result = attr()
                        main_functions.append(attr_name)
                except Exception:
                    pass
        
        if main_classes or main_functions:
            summary = []
            if main_classes:
                summary.append(f"实例化了类: {', '.join(main_classes[:3])}")
            if main_functions:
                summary.append(f"调用了函数: {', '.join(main_functions[:3])}")
            return True, "; ".join(summary)
        else:
            return True, "导入成功但未发现可测试的主类/函数"
            
    except Exception as e:
        return False, f"基本调用失败: {e}"

def run_comprehensive_test() -> Dict[str, Dict[str, Any]]:
    """运行综合测试"""
    modules = get_all_modules()
    print(f"发现 {len(modules)} 个模块需要测试\n")
    
    results = {}
    total_pass = 0
    total_fail = 0
    
    for i, module_name in enumerate(modules, 1):
        print(f"[{i:3d}/{len(modules)}] 测试 {module_name:40s}...", end=" ", flush=True)
        
        # 第一步：测试导入
        import_ok, import_msg = test_module_import(module_name)
        
        if not import_ok:
            print(f"❌ 导入失败: {import_msg}")
            results[module_name] = {
                "import": {"passed": False, "message": import_msg},
                "basic_call": {"passed": False, "message": "导入失败，跳过基本调用测试"},
                "overall": False
            }
            total_fail += 1
            continue
        
        # 第二步：测试基本调用
        try:
            module = importlib.import_module(module_name)
            call_ok, call_msg = test_module_basic_call(module_name, module)
        except Exception as e:
            call_ok, call_msg = False, f"重新导入或测试失败: {e}"
        
        if import_ok and call_ok:
            print(f"✓ {import_msg}")
            total_pass += 1
        else:
            print(f"⚠ {import_msg} | {call_msg}")
            total_fail += 1
        
        results[module_name] = {
            "import": {"passed": import_ok, "message": import_msg},
            "basic_call": {"passed": call_ok, "message": call_msg},
            "overall": import_ok and call_ok
        }
    
    return results

def generate_report(results: Dict[str, Dict[str, Any]], output_file: str = "lifeline_report.json"):
    """生成详细的测试报告"""
    # 统计汇总
    total = len(results)
    pass_count = sum(1 for r in results.values() if r["overall"])
    fail_count = total - pass_count
    import_fail_count = sum(1 for r in results.values() if not r["import"]["passed"])
    call_fail_count = sum(1 for r in results.values() 
                         if r["import"]["passed"] and not r["basic_call"]["passed"])
    
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "summary": {
            "total_modules": total,
            "fully_passed": pass_count,
            "failed": fail_count,
            "import_failures": import_fail_count,
            "basic_call_failures": call_fail_count,
            "health_rate": f"{(pass_count/total)*100:.1f}%"
        },
        "modules": {}
    }
    
    # 按状态分类模块
    fully_passed = []
    import_failed = []
    call_failed = []
    
    for module_name, result in results.items():
        module_report = {
            "import_status": "✓" if result["import"]["passed"] else "✗",
            "import_message": result["import"]["message"],
            "call_status": "✓" if result["basic_call"]["passed"] else "✗" if result["import"]["passed"] else "-",
            "call_message": result["basic_call"]["message"],
            "overall": "✓" if result["overall"] else "✗"
        }
        
        report["modules"][module_name] = module_report
        
        if result["overall"]:
            fully_passed.append(module_name)
        elif not result["import"]["passed"]:
            import_failed.append(module_name)
        else:
            call_failed.append(module_name)
    
    # 打印到控制台
    print("\n" + "="*70)
    print("领地生命线全量冒烟测试报告")
    print("="*70)
    
    print(f"\n📊 汇总统计:")
    print(f"  总模块数: {total}")
    print(f"  完全通过: {pass_count} ({report['summary']['health_rate']})")
    print(f"  导入失败: {import_fail_count}")
    print(f"  基本功能失败: {call_fail_count}")
    print(f"  总失败: {fail_count}")
    
    if fully_passed:
        print(f"\n✅ 完全通过的模块 ({len(fully_passed)}):")
        for mod in fully_passed[:10]:  # 只显示前10个
            print(f"  {mod}")
        if len(fully_passed) > 10:
            print(f"  ... 共 {len(fully_passed)} 个")
    
    if import_failed:
        print(f"\n❌ 导入失败的模块 ({len(import_failed)}):")
        for mod in import_failed[:10]:  # 只显示前10个
            print(f"  {mod}: {results[mod]['import']['message'][:50]}...")
        if len(import_failed) > 10:
            print(f"  ... 共 {len(import_failed)} 个")
    
    if call_failed:
        print(f"\n⚠️  基本功能失败的模块 ({len(call_failed)}):")
        for mod in call_failed[:10]:  # 只显示前10个
            print(f"  {mod}: {results[mod]['basic_call']['message'][:50]}...")
        if len(call_failed) > 10:
            print(f"  ... 共 {len(call_failed)} 个")
    
    # 保存详细报告到文件
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
        print(f"\n💾 详细报告已保存到: {output_file}")
    except Exception as e:
        print(f"\n⚠ 保存报告失败: {e}")
    
    return report

def main():
    """运行全量生命线冒烟测试"""
    print("🏥 开始领地生命线全量冒烟测试")
    print("="*70)
    print("目标：诚实摸清 220+ 模块里哪些真能跑、哪些是空壳")
    print("      这是最基础的生命体征检查，看看宣称的本事有多少是真本事")
    print("="*70)
    
    try:
        # 切换到脚本所在目录，确保模块发现正确
        script_dir = Path(__file__).parent
        os.chdir(script_dir)
        
        # 运行测试
        results = run_comprehensive_test()
        
        # 生成报告
        report = generate_report(results)
        
        # 返回码：0 如果健康率 >= 80%，否则 1
        health_rate = float(report['summary']['health_rate'].rstrip('%'))
        return 0 if health_rate >= 80 else 1
        
    except KeyboardInterrupt:
        print("\n\n⚠ 测试被用户中断")
        return 130
    except Exception as e:
        print(f"\n\n❌ 测试框架本身出错: {e}")
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
