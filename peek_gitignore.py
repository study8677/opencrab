import os

# 读取 .gitignore
gitignore_path = '.gitignore'
if os.path.exists(gitignore_path):
    with open(gitignore_path, 'r') as f:
        lines = f.readlines()
    print("=== .gitignore 内容 ===")
    for i, line in enumerate(lines, 1):
        print(f"行 {i}: {repr(line)}")
else:
    print(".gitignore 不存在")
