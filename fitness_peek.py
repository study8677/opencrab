"""检查 fitness.json 内容"""
from pathlib import Path
import json

fp = Path("fitness.json")
if fp.exists():
    data = json.loads(fp.read_text())
    print(f"keys: {list(data.keys())}")
    print(f"score: {data.get('score')}")
    print(f"pass_rate: {data.get('pass_rate')}")
    print(f"runs: {len(data.get('runs', []))}")
else:
    print("fitness.json 不存在")
