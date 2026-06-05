import json
from pathlib import Path

fitness_path = Path("fitness.json")
if fitness_path.exists():
    with open(fitness_path) as f:
        data = json.load(f)
    print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    print("fitness.json 不存在")
