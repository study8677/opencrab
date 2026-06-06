import planner, intent, heartbeat, projects, os, subprocess

# 1. 看 planner.form_intent 签名
import inspect
print("=== planner.form_intent ===")
print(inspect.getsource(planner.form_intent))

# 2. 看 state/projects 目录结构
state_dir = "state/projects"
if os.path.exists(state_dir):
    for pid in os.listdir(state_dir):
        goal_path = os.path.join(state_dir, pid, "goal.md")
        if os.path.exists(goal_path):
            print(f"\n=== {goal_path} ===")
            with open(goal_path) as f:
                print(f.read())
else:
    print(f"\n{state_dir}/ 不存在")

# 3. 看 heartbeat.py 里的 git diff --cached 检查
print("\n=== heartbeat.py 中的 git diff 检查 ===")
with open("heartbeat.py") as f:
    content = f.read()
    # 找 git diff --cached 相关行
    for i, line in enumerate(content.split('\n')):
        if 'diff' in line.lower() or 'cached' in line.lower() or 'journal' in line.lower():
            print(f"{i}: {line}")
