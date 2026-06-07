import os

# 检查 state/projects/ 目录
state_projects_path = 'state/projects/'
if os.path.exists(state_projects_path):
    print(f"=== state/projects/ 内容 ===")
    for f in os.listdir(state_projects_path):
        print(f"  {f}")
else:
    print("state/projects/ 目录不存在")

# 检查 state 目录
state_path = 'state/'
if os.path.exists(state_path):
    print(f"\n=== state/ 内容 ===")
    for f in os.listdir(state_path):
        print(f"  {f}")
else:
    print("state/ 目录不存在")
