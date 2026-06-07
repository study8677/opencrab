#!/usr/bin/env python3
"""读取canary_75_real_weld.py焊接流程"""
from pathlib import Path

def check():
    p = Path("canary_75_real_weld.py")
    if not p.exists():
        print("❌ canary_75_real_weld.py 不存在")
        return
    
    content = p.read_text()
    print(f"=== canary_75_real_weld.py 内容 ({len(content)}字符) ===")
    print(content)

if __name__ == "__main__":
    check()
