"""发布彩排：跑通 branchlab→canary→releasegate 断奶改动流程。"""

from __future__ import annotations

import sys
import traceback
from typing import List, Tuple

import branchlab
import canary
import releasegate


def run_rehearsal() -> Tuple[bool, List[str]]:
    """执行一次完整的发布彩排。"""
    log: List[str] = []

    # 1. 通过 branchlab 创建断奶分支
    log.append("[1/3] 通过 branchlab 创建断奶分支...")
    try:
        branch_result = branchlab.create_weaning_branch()
        log.append(f"  branchlab 结果: {branch_result}")
    except Exception as e:
        log.append(f"  branchlab 失败: {e}")
        return False, log

    # 2. 运行 canary 测试
    log.append("[2/3] 运行 canary 测试...")
    try:
        canary_result = canary.run_canary()
        log.append(f"  canary 结果: {canary_result}")
    except Exception as e:
        log.append(f"  canary 失败: {e}")
        return False, log

    # 3. 通过 releasegate 检查
    log.append("[3/3] 通过 releasegate 闸门检查...")
    try:
        gate_result = releasegate.check()
        log.append(f"  releasegate 结果: {gate_result}")
    except Exception as e:
        log.append(f"  releasegate 失败: {e}")
        return False, log

    success = all([branch_result, canary_result, gate_result])
    return success, log


def main() -> int:
    """主函数：执行彩排并报告结果。"""
    print("=== 发布彩排开始 ===")
    success, log = run_rehearsal()

    for line in log:
        print(line)

    if success:
        print("\n✅ 彩排成功！所有闸门通过。")
        return 0
    else:
        print("\n❌ 彩排失败，请检查上述错误。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
