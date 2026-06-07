#!/usr/bin/env python3
"""解封 state/ 并提交 projects 账本"""
import subprocess
import sys
from pathlib import Path

GITIGNORE = Path(".gitignore")
TARGET = "state/projects/项目账.md"
COMMIT_MSG = """feat: 解封 state/projects/ 接入 git 追踪

跨心跳路线图终于接通——项目账正式被 git 接管，不再被潮汐抹平。

验证: git diff --cached --stat"""

def run(cmd, check=True):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"FAIL: {cmd}")
        print(result.stderr)
        sys.exit(1)
    return result

def edit_gitignore_line11():
    """把 .gitignore 第 11 行的 state/ 封印注释掉"""
    lines = GITIGNORE.read_text().splitlines(keepends=True)
    if len(lines) < 11:
        print("ERROR: .gitignore 只有 {} 行".format(len(lines)))
        sys.exit(1)
    # 第 11 行索引为 10
    line11 = lines[10]
    if not line11.strip().startswith("#"):
        lines[10] = "# " + line11
        GITIGNORE.write_text("".join(lines))
        print("已封印第 11 行: {}".format(line11.rstrip()))
    else:
        print("第 11 行已是注释: {}".format(line11.rstrip()))

def main():
    print("=== 1. 解封 .gitignore 第 11 行 ===")
    edit_gitignore_line11()

    print("\n=== 2. git add {} ===".format(TARGET))
    run("git add " + TARGET)
    print("add 成功")

    print("\n=== 3. git commit ===")
    run("git commit -m '{}'".format(COMMIT_MSG))
    print("commit 成功")

    print("\n=== 4. 验证 git diff --cached --stat ===")
    result = run("git diff --cached --stat", check=False)
    print(result.stdout)

if __name__ == "__main__":
    main()
