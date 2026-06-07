#!/usr/bin/env python3
"""
诊断脚本：亲手跑 canary.py，捕获 stdout / stderr / 退出码
"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent
CANARY = REPO_ROOT / "canary.py"

def run_canary():
    print("=" * 60)
    print("开始运行 canary.py")
    print("=" * 60)
    
    # 捕获所有输出
    result = subprocess.run(
        [sys.executable, str(CANARY)],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT)
    )
    
    print("\n--- STDOUT ---")
    print(result.stdout if result.stdout else "(空)")
    
    print("\n--- STDERR ---")
    print(result.stderr if result.stderr else "(空)")
    
    print(f"\n--- 退出码: {result.returncode} ---")
    
    # 分析结果
    print("\n" + "=" * 60)
    print("诊断结论:")
    print("=" * 60)
    
    if result.returncode == 0:
        print("✅ 退出码 0：正常退出")
    else:
        print(f"❌ 退出码 {result.returncode}：非正常退出")
    
    if result.stderr:
        print("❌ 有 stderr 输出，可能有异常或警告")
    else:
        print("✅ 无 stderr 输出")
    
    # 尝试解析 stdout 中的结果
    if "passed" in result.stdout or "failed" in result.stdout:
        print("✅ 有结果输出")
        for line in result.stdout.split("\n"):
            if "passed" in line or "failed" in line or "total" in line:
                print(f"   {line}")
    else:
        print("❌ 无结果输出，可能崩溃在检查途中")
    
    return result

if __name__ == "__main__":
    run_canary()
