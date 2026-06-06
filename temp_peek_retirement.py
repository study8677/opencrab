#!/usr/bin/env python3
"""临时 peek retirement_drill.py 接口"""
import pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))

REPO_ROOT = pathlib.Path(__file__).resolve().parent

# 读 retirement_drill.py 找函数签名
text = (REPO_ROOT / "retirement_drill.py").read_text()
import re
funcs = re.findall(r'^def (\w+)\(.*?\).*?(?=\n(?:def |class |\Z))', text, re.MULTILINE | re.DOTALL)
for f in funcs[:10]:
    print(f)
    
# 读 audit.py 找 30 天零调用记录的逻辑
audit_text = (REPO_ROOT / "audit.py").read_text()
if '30' in audit_text or 'thirty' in audit_text.lower() or 'zero' in audit_text.lower():
    print("=== audit.py has time/threshold logic ===")
    
# 找 import 分析相关代码
for fname in ["readpack.py", "read_state.py"]:
    t = (REPO_ROOT / fname).read_text()
    print(f"\n=== {fname} first 50 lines ===")
    print('\n'.join(t.splitlines()[:50]))
