#!/usr/bin/env python3
"""临时脚本：读取 fitness.json"""
from pathlib import Path
import json

p = Path("fitness.json")
if p.exists():
    content = json.loads(p.read_text())
    print("=== fitness.json ===")
    print(json.dumps(content, indent=2))
else:
    print("❌ fitness.json 不存在")
