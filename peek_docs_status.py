#!/usr/bin/env python3
"""快速检查 docs/index.html 当前状态。"""
import os, re

html = open('docs/index.html').read()
print("=== docs/index.html 当前橱窗数字 ===")
for m in re.findall(r'(\d+)\s*(个模块|篇航海日志|个技能)', html):
    print(m)

# 实际统计
import subprocess

py_files = [f for f in os.listdir('.') if f.endswith('.py') and f != '__init__.py' and not f.startswith('test_')]
print(f"\n实际 .py 模块数: {len(py_files)}")

try:
    commits = subprocess.run(['git', 'rev-list', '--count', 'HEAD'], capture_output=True, text=True).stdout.strip()
    print(f"实际 git 提交数: {commits}")
except:
    print("git 失败")

# 检查 skillgraph.py
if os.path.exists('skillgraph.py'):
    content = open('skillgraph.py').read()
    skill_fns = re.findall(r'def\s+[_\w]*skill[_\w]*\(', content)
    print(f"skillgraph.py 中的 skill 函数数: {len(skill_fns)}")
