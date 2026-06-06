#!/usr/bin/env python3
"""运行尸检并输出结果"""
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

def main():
    print("=" * 70)
    print("🔬 运行 canary 75% 失败根因尸检")
    print("=" * 70)

    # 先检查 fitness.json 是否存在
    fp = REPO_ROOT / "fitness.json"
    if not fp.exists():
        print("\n❌ fitness.json 不存在！需要先建立基准")
        print("   运行: python run_fitness_baseline.py 或类似脚本")
        return 1

    # 运行尸检
    result = subprocess.run(
        [sys.executable, "autopsy_do_canary_75_final.py"],
        cwd=REPO_ROOT,
    )
    return result.returncode

if __name__ == "__main__":
    sys.exit(main())
