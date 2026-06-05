import subprocess
result = subprocess.run(['python', '-c', '''
import json
# 读取账本
with open("projects账本.json", "r") as f:
    ledger = json.load(f)
print("=== 账本结构 ===")
print(f"项目数: {len(ledger.get("projects", []))}")
for p in ledger.get("projects", [])[:3]:
    print(f"  - {p.get("name", "unnamed")}: {p.get("status", "unknown")}")

# 读取 fitness 基线
import os
if os.path.exists("fitness_ledger.json"):
    with open("fitness_ledger.json", "r") as f:
        baseline = json.load(f)
    print("\n=== Fitness 基线 ===")
    for run in baseline.get("runs", [])[-3:]:
        print(f"  {run.get("timestamp", "unknown")}: {run.get("summary", {})}")

# 读取 bootstrap_fitness.py 看最弱方向
with open("bootstrap_fitness.py", "r") as f:
    content = f.read()
print("\n=== bootstrap_fitness.py 前50行 ===")
print("\\n".join(content.split("\\n")[:50]))
'''], capture_output=True, text=True)
print(result.stdout)
print(result.stderr)
