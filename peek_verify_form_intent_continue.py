#!/usr/bin/env python3
"""临时脚本：读取并执行 verify_form_intent_continue.py 的内容"""
import os, sys

# 读取源码
src = os.path.join(os.path.dirname(__file__), 'verify_form_intent_continue.py')
with open(src) as f:
    content = f.read()

print("=" * 60)
print("verify_form_intent_continue.py 源码预览:")
print("=" * 60)
print(content[:3000])  # 先看前3k字符
print("...")
print("=" * 60)

# 执行它
print("\n>>> 执行 verify_form_intent_continue.py:")
print("=" * 60)
exec(compile(content, src, 'exec'), {'__name__': '__main__', '__file__': src})
