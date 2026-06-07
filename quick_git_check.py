#!/usr/bin/env python3
"""快速验证：state/projects/ 是否被 git 跟踪"""
import subprocess
import os

def check_tracking(path):
    """检查路径是否被 git 跟踪"""
    # 先检查是否被忽略
    r1 = subprocess.run(['git', 'check-ignore', '-v', path], capture_output=True)
    ignored = r1.returncode == 0
    
    # 再检查是否被跟踪
    r2 = subprocess.run(['git', 'ls-files', path], capture_output=True, text=True)
    tracked = bool(r2.stdout.strip())
    
    return ignored, tracked

# 检查链
for path in ['state/', 'state/projects/', 'state/projects/项目账.md']:
    ignored, tracked = check_tracking(path)
    status = "✅ tracked" if tracked else ("🚫 ignored" if ignored else "❌ not exist")
    print(f"{status}: {path}")
