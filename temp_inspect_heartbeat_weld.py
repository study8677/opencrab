import json, sys

# 检查 run_incomplete_heartbeat_weld_to_done.py
with open('run_incomplete_heartbeat_weld_to_done.py') as f:
    print("=== run_incomplete_heartbeat_weld_to_done.py ===")
    print(f.read())

# 检查 heartbeat.py
with open('heartbeat.py') as f:
    print("\n=== heartbeat.py ===")
    print(f.read())

# 检查 projects.py 找 ledger 相关
with open('projects.py') as f:
    content = f.read()
    # 找 ledger 写入逻辑
    lines = content.split('\n')
    for i, line in enumerate(lines):
        if 'ledger' in line.lower() or 'DONE' in line:
            print(f"{i}: {line}")
