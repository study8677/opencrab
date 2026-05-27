import traceback
from typing import Any, Dict, Optional

# 假设 hands.py 中有 apply_patch 函数，用于应用补丁
# 假设 replay.py 中有 replay_old_failure 函数，用于验收旧失败
def apply_patch_stub(patch: Dict[str, Any]) -> bool:
    """临时桩函数，实际应从 hands 导入。"""
    # 这里应替换为实际的 apply_patch 逻辑
    print("Stub: Applying patch")
    return True  # 假设成功

def replay_old_failure_stub(old_failure: Dict[str, Any]) -> bool:
    """临时桩函数，实际应从 replay 导入。"""
    # 这里应替换为实际的 replay 逻辑
    print("Stub: Replaying old failure")
    return True  # 假设成功

def try_patch_with_retry(
    patch: Dict[str, Any],
    old_failure: Optional[Dict[str, Any]] = None,
    max_retries: int = 1
) -> bool:
    """
    尝试应用补丁，如果失败，自动缩小补丁范围并重试一次。
    使用旧失败 replay 来验收。
    
    Args:
        patch: 补丁内容，例如 {'changes': [{'file': 'x.py', 'diff': '...'}, ...]}。
        old_failure: 旧的失败案例数据，用于验收。
        max_retries: 最大重试次数，默认为1（即总共尝试两次）。
    
    Returns:
        bool: 是否成功应用补丁并通过验收。
    """
    current_patch = patch.copy()
    for attempt in range(max_retries + 1):
        try:
            # 尝试应用补丁
            success = apply_patch_stub(current_patch)
            if success:
                # 如果应用成功，用旧失败 replay 验收
                if old_failure:
                    replay_success = replay_old_failure_stub(old_failure)
                    if replay_success:
                        print(f"Patch applied and replay passed on attempt {attempt}")
                        return True
                    else:
                        print(f"Patch applied but replay failed on attempt {attempt}")
                        if attempt == max_retries:
                            return False
                        # 缩小补丁范围并重试
                        current_patch = shrink_patch(current_patch)
                else:
                    print(f"Patch applied successfully on attempt {attempt}")
                    return True
            else:
                print(f"Patch application failed on attempt {attempt}")
                if attempt == max_retries:
                    return False
                current_patch = shrink_patch(current_patch)
        except Exception as e:
            print(f"Exception on attempt {attempt}: {e}")
            traceback.print_exc()
            if attempt == max_retries:
                return False
            current_patch = shrink_patch(current_patch)
    return False

def shrink_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    缩小补丁范围：移除补丁中的最后一个变更（如果存在多个变更）。
    这样逐步减少修改范围以提高成功率。
    
    Args:
        patch: 原始补丁字典。
    
    Returns:
        Dict[str, Any]: 缩小后的补丁；若只有一个变更，则返回原补丁。
    """
    if 'changes' in patch and isinstance(patch['changes'], list) and len(patch['changes']) > 1:
        new_patch = patch.copy()
        new_patch['changes'] = patch['changes'][:-1]
        print(f"Shrunk patch: removed last change, now {len(new_patch['changes'])} changes")
        return new_patch
    else:
        print("Cannot shrink patch further (only one or no change)")
        return patch
