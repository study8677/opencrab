"""
读取evalbench基线分数，挑出得分最低的黄金任务，然后用readpack读取对应模块代码。
"""
import importlib
import sys
from pathlib import Path
from typing import Dict, Any

# 假设evalbench.py中有一个函数get_baseline_scores返回基线分数
# 假设每个任务对应一个模块，任务名就是模块名
def readpack_evalbench():
    # 读取evalbench.py内容
    evalbench_content = Path("evalbench.py").read_text(encoding="utf-8")
    print("=== evalbench.py 结构预览 ===")
    print(evalbench_content[:2000])  # 只打印前2000字符
    
    # 尝试导入evalbench模块
    try:
        evalbench = importlib.import_module("evalbench")
    except ImportError as e:
        print(f"无法导入evalbench: {e}")
        return
    
    # 检查是否有获取基线分数的方法
    if hasattr(evalbench, "get_baseline_scores"):
        scores = evalbench.get_baseline_scores()
    elif hasattr(evalbench, "EvalBench"):
        # 假设有一个EvalBench类
        bench = evalbench.EvalBench()
        scores = bench.run_baseline()
    else:
        print("未找到获取基线分数的方法")
        # 假设一个默认的分数字典用于演示
        scores = {
            "triage.py": 45.2,
            "calibration.py": 78.9,
            "compass.py": 62.1,
            "driftwatch.py": 89.3
        }
    
    # 找出得分最低的任务
    min_task = min(scores.items(), key=lambda x: x[1])
    print(f"\n=== 得分最低的黄金任务 ===")
    print(f"任务: {min_task[0]}, 分数: {min_task[1]}")
    
    # 用readpack读取对应模块代码
    module_name = min_task[0]
    if module_name.endswith(".py"):
        module_name = module_name[:-3]
    
    try:
        # 读取模块文件内容
        module_path = Path(f"{module_name}.py")
        if module_path.exists():
            content = module_path.read_text(encoding="utf-8")
            print(f"\n=== {module_name}.py 内容 ===")
            print(content[:3000])  # 打印前3000字符
            return module_name, content
        else:
            print(f"模块文件 {module_name}.py 不存在")
            return None, None
    except Exception as e:
        print(f"读取模块时出错: {e}")
        return None, None

if __name__ == "__main__":
    readpack_evalbench()
