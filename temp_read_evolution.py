#!/usr/bin/env python3
"""临时脚本：读取 DO_CANARY_80_EVOLUTION.py 源码"""
from pathlib import Path

p = Path("DO_CANARY_80_EVOLUTION.py")
if p.exists():
    content = p.read_text()
    print(f"=== DO_CANARY_80_EVOLUTION.py ({len(content)} chars) ===")
    print(content)
else:
    print("❌ DO_CANARY_80_EVOLUTION.py 不存在")
