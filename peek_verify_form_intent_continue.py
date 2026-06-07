import os

# 读取 verify_form_intent_continue.py
verify_path = 'verify_form_intent_continue.py'
if os.path.exists(verify_path):
    with open(verify_path, 'r') as f:
        content = f.read()
    print("=== verify_form_intent_continue.py 完整内容 ===")
    print(content)
else:
    print("verify_form_intent_continue.py 不存在")
