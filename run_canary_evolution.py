#!/usr/bin/env python3
"""
主脚本：执行完整的 canary 缺陷修复流程
"""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).parent

def run_step(name, script):
    """运行一个步骤"""
    print(f"\n{'='*60}")
    print(f"▶ 步骤: {name}")
    print(f"{'='*60}")
    result = subprocess.run(
        ["python", str(REPO / script)],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr}")
    if result.returncode != 0:
        print(f"❌ 步骤 {name} 失败 (code={result.returncode})")
        return False
    return True

def main():
    print("🚀 开始 canary.py 缺陷修复流程")
    print("   目标: 定位永恒 True bug，brain-only 产 patch，过 3 闸 + 3x 复现，焊 git")
    
    steps = [
        ("1. astlocator 定位真缺陷", "astlocator_canary_realdefect.py"),
        ("2. brain-only 产 patch", "brainonly_canary_patch.py"),
        ("3. 第一闸: 语法+导入", "check_three_gates_canary.py"),
        ("4. 第二闸: 逻辑已修复", "check_three_gates_canary.py"),
        ("5. 第三闸: 运行正常", "check_three_gates_canary.py"),
        ("6. 3x 复现验证", "reproduce_canary_3x.py"),
        ("7. Git 焊进", "git_commit_canary_fix.py"),
    ]
    
    # 执行关键步骤
    if not run_step(steps[0][0], steps[0][1]):
        sys.exit(1)
    
    if not run_step(steps[1][0], steps[1][1]):
        sys.exit(1)
    
    # 3 闸一起跑
    print(f"\n{'='*60}")
    print("▶ 步骤: 3 闸检查")
    print(f"{'='*60}")
    result = subprocess.run(
        ["python", str(REPO / "check_three_gates_canary.py")],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(f"❌ 3闸检查失败")
        sys.exit(1)
    print("✅ 3闸全过！")
    
    # 3x 复现
    if not run_step(steps[5][0], steps[5][1]):
        sys.exit(1)
    
    # Git
    run_step(steps[6][0], steps[6][1])
    
    print(f"\n{'='*60}")
    print("🎉 canary.py 缺陷修复流程完成！")
    print(f"{'='*60}")

if __name__ == "__main__":
    main()
