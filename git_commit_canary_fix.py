"""
Git 焊进：diff 提交到 git
"""
import subprocess
from pathlib import Path

REPO = Path(__file__).parent
PATCH = REPO / "canary_fix.patch"
CANARY = REPO / "canary.py"

def git_commit_fix():
    """将修复提交到 git"""
    
    # 1. 确认 git 状态
    status = subprocess.run(
        ["git", "status", "--short"],
        cwd=REPO,
        capture_output=True,
        text=True
    )
    print(f"Git 状态:\n{status.stdout}")
    
    # 2. 检查 diff
    diff = subprocess.run(
        ["git", "diff", "canary.py"],
        cwd=REPO,
        capture_output=True,
        text=True
    )
    if diff.stdout:
        print(f"\nCanary.py 的 diff:\n{diff.stdout[:500]}...")
    
    # 3. 添加并提交
    subprocess.run(["git", "add", "canary.py", str(PATCH)], cwd=REPO, capture_output=True)
    
    commit = subprocess.run(
        [
            "git", "commit", "-m",
            "fix(canary): 修复 _check_recent_activity 永恒 True bug\n\n"
            "缺陷: return len(...) >= 0 永远返回 True\n"
            "修复: 改为 > 0，至少一个文件才算有活动\n\n"
            "验证: 通过 3 闸 + 3x 复现"
        ],
        cwd=REPO,
        capture_output=True,
        text=True
    )
    
    if commit.returncode == 0:
        print(f"\n✅ 已提交: {commit.stdout}")
        # 显示提交记录
        log = subprocess.run(
            ["git", "log", "-1", "--oneline"],
            cwd=REPO,
            capture_output=True,
            text=True
        )
        print(f"提交: {log.stdout}")
    else:
        print(f"\n⚠️ 提交失败或无可提交内容: {commit.stderr}")
        print("（可能文件未变化，或已提交过）")

if __name__ == "__main__":
    git_commit_fix()
