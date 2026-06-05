import json
from pathlib import Path

weakest_path = Path("state/projects/weakest-cells.json")
if weakest_path.exists():
    with open(weakest_path) as f:
        data = json.load(f)
    print(json.dumps(data, indent=2, ensure_ascii=False))
else:
    print("weakest-cells.json 不存在")
    # 看看有没有其他相关文件
    state_dir = Path("state/projects")
    if state_dir.exists():
        for p in state_dir.iterdir():
            print(f"  {p.name}")
