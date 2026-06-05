#!/usr/bin/env python3
"""临时查看关键文件"""
import json
from pathlib import Path

# 读取账本
ledger_path = Path("projects账本.json")
if ledger_path.exists():
    with open(ledger_path) as f:
        ledger = json.load(f)
    print("=== projects账本.json 结构 ===")
    print(json.dumps(ledger, indent=2, ensure_ascii=False)[:3000])
else:
    print("账本不存在")

# 查看 form_intent 在哪里定义
import subprocess
result = subprocess.run(['grep', '-rn', 'def form_intent', '.'], 
                       capture_output=True, text=True, cwd='.')
print("\n=== form_intent 定义位置 ===")
print(result.stdout[:2000])
