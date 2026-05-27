"""
重复采样工具，用于区分偶发失败与真实退化。
通过多次运行同一操作，统计通过率来判断抖动。
"""
from __future__ import annotations
import statistics
from typing import Callable, Any

def resample(
    func: Callable[..., Any],
    *args: Any,
    n_times: int = 3,
    required_pass_ratio: float = 0.6,
    **kwargs: Any,
) -> dict[str, Any]:
    """
    重复运行函数，收集结果，判断是否为抖动。

    Args:
        func: 要重复运行的函数
        *args, **kwargs: 传给 func 的参数
        n_times: 重复次数
        required_pass_ratio: 通过率阈值，低于此值视为真失败

    Returns:
        {
            'success': bool,  # 最终判定是否通过（考虑抖动容忍）
            'details': list[bool],  # 每次运行的通过/失败记录
            'pass_rate': float,  # 通过率
            'is_jitter': bool,  # 是否为抖动（偶发失败）
            'stats': {
                'total': int,
                'passed': int,
                'failed': int,
            }
        }
    """
    results: list[bool] = []
    for i in range(n_times):
        try:
            res = func(*args, **kwargs)
            # 简单约定：函数返回 truthy 值视为成功
            results.append(bool(res))
        except Exception:
            results.append(False)

    passed = sum(results)
    total = len(results)
    pass_rate = passed / total if total > 0 else 0.0

    # 真退化：通过率不足阈值
    # 偶发失败：通过率足够高但不是100%
    is_jitter = (pass_rate >= required_pass_ratio) and (passed < total)
    success = pass_rate >= required_pass_ratio

    return {
        'success': success,
        'details': results,
        'pass_rate': pass_rate,
        'is_jitter': is_jitter,
        'stats': {
            'total': total,
            'passed': passed,
            'failed': total - passed,
        }
    }

def quick_resample(
    func: Callable[..., Any],
    *args: Any,
    n_times: int = 3,
    **kwargs: Any,
) -> bool:
    """快速版本，仅返回最终判定（是否通过）"""
    result = resample(func, *args, n_times=n_times, **kwargs)
    return result['success']
