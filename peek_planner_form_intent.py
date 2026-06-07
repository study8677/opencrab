import os
import sys

# 读取 planner.py 中的 form_intent 函数
planner_path = 'planner.py'
if os.path.exists(planner_path):
    with open(planner_path, 'r') as f:
        content = f.read()
    print("=== planner.py 中 form_intent 函数 ===")
    # 找到 form_intent 函数
    import re
    match = re.search(r'def form_intent\(.*?\).*?(?=\n(?:def |class |\Z))', content, re.DOTALL)
    if match:
        print(match.group(0)[:3000])
    else:
        print("未找到 form_intent 函数")
else:
    print("planner.py 不存在")
