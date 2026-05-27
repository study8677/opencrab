import traceback
from typing import Any, Dict, List, Optional

# 假设 hands.py 中有 apply_patch 函数，用于应用补丁
# 假设 replay.py 中有 replay_old_failure 函数，用于验收旧失败
def apply_patch_stub(patch: Dict[str, Any]) -> bool:
    """临时桩函数，实际应从 hands 导入。"""
    # 这里应替换为实际的 apply_patch 逻辑
    print("Stub: Applying patch")
    return True  # 假设成功

def replay_old_failure_stub(old_failure: Dict[str, Any]) -> Dict[str, Any]:
    """临时桩函数，实际应从 replay 导入。
    现在返回详细信息：{'success': bool, 'errors': [{'file': str, 'line': int, 'msg': str}]}
    """
    print("Stub: Replaying old failure")
    # 模拟成功的验收
    return {'success': True, 'errors': []}

def analyze_failure_reason(errors: List[Dict[str, Any]]) -> str:
    """分析失败原因，返回一个简短的失败类型标签，用于针对性微调。
    
    Args:
        errors: 验收返回的错误列表，每个错误至少包含 file, line, msg 字段。
        
    Returns:
        str: 失败类型标签，例如 'syntax_error', 'import_error', 'runtime_error', 'unknown'
    """
    if not errors:
        return 'unknown'
    
    # 统计最常见的错误类型
    error_types = []
    for err in errors:
        msg = err.get('msg', '').lower()
        if 'syntax' in msg or 'invalid syntax' in msg:
            error_types.append('syntax_error')
        elif 'import' in msg or 'module not found' in msg:
            error_types.append('import_error')
        elif 'runtime' in msg or 'error' in msg:
            error_types.append('runtime_error')
        else:
            error_types.append('unknown')
    
    # 返回最常见的错误类型
    from collections import Counter
    counter = Counter(error_types)
    most_common = counter.most_common(1)
    return most_common[0][0] if most_common else 'unknown'

def targeted_shrink_patch(patch: Dict[str, Any], error_type: str) -> Dict[str, Any]:
    """根据失败原因，针对性地微调补丁。
    
    Args:
        patch: 原始补丁字典，格式为 {'changes': [{'file': '...', 'diff': '...'}, ...]}
        error_type: analyze_failure_reason 返回的错误类型标签
        
    Returns:
        Dict[str, Any]: 微调后的补丁
    """
    if 'changes' not in patch or not isinstance(patch['changes'], list):
        return patch
    
    changes = patch['changes']
    if len(changes) <= 1:
        return patch  # 无法进一步缩减
    
    new_changes = []
    
    if error_type == 'syntax_error':
        # 语法错误：只保留第一个变更（最基础的变更）
        new_changes = changes[:1]
        print(f"Targeted shrink for syntax error: kept {len(new_changes)} of {len(changes)} changes")
    elif error_type == 'import_error':
        # 导入错误：移除可能影响导入的变更（这里简化处理：移除最后两个变更）
        keep_count = max(1, len(changes) - 2)
        new_changes = changes[:keep_count]
        print(f"Targeted shrink for import error: kept {len(new_changes)} of {len(changes)} changes")
    else:
        # 其他错误：使用原来的 shrink 策略（移除最后一个变更）
        new_changes = changes[:-1]
        print(f"Targeted shrink for {error_type}: removed last change, now {len(new_changes)} changes")
    
    new_patch = patch.copy()
    new_patch['changes'] = new_changes
    return new_patch

def try_patch_with_retry(
    patch: Dict[str, Any],
    old_failure: Optional[Dict[str, Any]] = None,
    max_retries: int = 1
) -> bool:
    """
    尝试应用补丁，如果失败，自动分析失败原因、微调补丁并重试。
    使用旧失败 replay 来验收，现在能获取详细的错误信息。
    
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
            # 1. 尝试应用补丁
            success = apply_patch_stub(current_patch)
            if not success:
                print(f"Patch application failed on attempt {attempt}")
                if attempt == max_retries:
                    return False
                # 应用失败：直接使用简单缩减（无法分析验收错误）
                current_patch = shrink_patch(current_patch)
                continue
            
            # 2. 应用成功，用旧失败 replay 验收
            if old_failure:
                replay_result = replay_old_failure_stub(old_failure)
                # 兼容旧版返回bool的情况
                if isinstance(replay_result, bool):
                    replay_success = replay_result
                    errors = []
                else:
                    replay_success = replay_result.get('success', False)
                    errors = replay_result.get('errors', [])
                
                if replay_success:
                    print(f"Patch applied and replay passed on attempt {attempt}")
                    return True
                else:
                    print(f"Patch applied but replay failed on attempt {attempt}")
                    if errors:
                        error_type = analyze_failure_reason(errors)
                        print(f"Failure reason detected: {error_type}")
                    
                    if attempt == max_retries:
                        return False
                    
                    # 根据失败原因针对性微调
                    if errors and error_type != 'unknown':
                        current_patch = targeted_shrink_patch(current_patch, error_type)
                    else:
                        current_patch = shrink_patch(current_patch)
            else:
                # 没有旧失败数据，只检查应用成功
                print(f"Patch applied successfully on attempt {attempt} (no old failure to replay)")
                return True
                
        except Exception as e:
            print(f"Exception on attempt {attempt}: {e}")
            traceback.print_exc()
            if attempt == max_retries:
                return False
            # 异常时使用简单缩减
            current_patch = shrink_patch(current_patch)
    
    return False

def shrink_patch(patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    缩小补丁范围：移除补丁中的最后一个变更（如果存在多个变更）。
    这是通用的缩减策略，用于无法分析失败原因时。
    
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
