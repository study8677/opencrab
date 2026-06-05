import os

# 读取 fitness.md
fitness_path = "state/projects/fitness.md"
if os.path.exists(fitness_path):
    with open(fitness_path) as f:
        print("=== state/projects/fitness.md ===")
        print(f.read())
else:
    print(f"File not found: {fitness_path}")
