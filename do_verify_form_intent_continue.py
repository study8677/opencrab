"""运行 verify_form_intent_continue.py 并输出真实信号"""
import sys
import os

# 先打印环境状态
print("=" * 60)
print("诊断：form_intent 真实信号")
print("=" * 60)

# 检查 state/projects/ 是否在 .gitignore 中
import subprocess
result = subprocess.run(['git', 'check-ignore', '-v', 'state/projects/'],
                       capture_output=True, text=True)
if result.returncode == 0:
    print(f"⚠️  state/projects/ 在 .gitignore 中: {result.stdout.strip()}")
else:
    print("✅ state/projects/ 不在 .gitignore 中（正常）")

# 检查 state/projects/ 是否存在
if os.path.exists('state/projects/'):
    projects = os.listdir('state/projects/')
    print(f"📁 state/projects/ 存在，项目: {projects}")
else:
    print("❌ state/projects/ 不存在")

print("-" * 60)

# 运行原始 verify 脚本
sys.path.insert(0, os.path.dirname(__file__))
from verify_form_intent_continue import verify

print("\n运行 verify_form_intent_continue.py ...")
result = verify()
sys.exit(0 if result else 1)
