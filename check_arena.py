#!/usr/bin/env python3
"""检查 arena 模块"""
import sys
sys.path.insert(0, '.')
import inspect

# 尝试导入各模块
for mod_name in ['arena', 'boundaryeval', 'regression', 'canary']:
    try:
        mod = __import__(mod_name)
        print(f"\n=== {mod_name} 可导入 ===")
        # 找主函数
        if hasattr(mod, 'run') or hasattr(mod, 'evaluate') or hasattr(mod, 'fitness'):
            for fn in ['run', 'evaluate', 'fitness', 'score', 'eval']:
                if hasattr(mod, fn):
                    print(f"  发现函数: {fn}")
                    print(inspect.getsource(getattr(mod, fn))[:500])
    except Exception as e:
        print(f"\n=== {mod_name} 导入失败: {e} ===")
