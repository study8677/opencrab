#!/usr/bin/env python3
"""读取autopsy_do_canary_75_final.py钉的真缺陷"""
from pathlib import Path

def check():
    p = Path("autopsy_do_canary_75_final.py")
    if not p.exists():
        print("❌ autopsy_do_canary_75_final.py 不存在")
        return
    
    content = p.read_text()
    print(f"=== autopsy_do_canary_75_final.py 内容 ({len(content)}字符) ===")
    print(content)
    
    # 提取关键缺陷点
    print("\n=== 关键缺陷摘要 ===")
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if any(kw in line.lower() for kw in ['defect', 'bug', 'fix', 'patch', 'issue', 'real']):
            print(f"  L{i+1}: {line.strip()}")

if __name__ == "__main__":
    check()
