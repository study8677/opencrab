#!/usr/bin/env python3
"""快速读取fitness.json核真分"""
import json
from pathlib import Path

def peek():
    p = Path("fitness.json")
    if not p.exists():
        print("❌ fitness.json 不存在")
        return
    
    data = json.loads(p.read_text())
    print(f"=== fitness.json 当前状态 ===")
    
    # 找canary相关格子
    canary_keys = [k for k in data.keys() if 'canary' in k.lower()]
    for k in sorted(canary_keys):
        print(f"  {k}: {data[k]}")
    
    # 也打印全部key看结构
    print(f"\n全部keys({len(data)}个):")
    for k in sorted(data.keys()):
        print(f"  {k}: {data[k]}")

if __name__ == "__main__":
    peek()
