"""
测试 resample 模块的功能
"""
import pytest
from resample import resample, quick_resample

def test_resample_success():
    """测试始终通过的情况"""
    def always_pass():
        return True
    
    result = resample(always_pass, n_times=5)
    assert result['success'] == True
    assert result['is_jitter'] == False
    assert result['pass_rate'] == 1.0

def test_resample_failure():
    """测试始终失败的情况"""
    def always_fail():
        return False
    
    result = resample(always_fail, n_times=5)
    assert result['success'] == False
    assert result['is_jitter'] == False
    assert result['pass_rate'] == 0.0

def test_resample_jitter():
    """测试抖动情况（偶发失败）"""
    call_count = 0
    
    def sometimes_fail():
        nonlocal call_count
        call_count += 1
        # 第一次失败，其他通过
        return call_count != 1
    
    result = resample(sometimes_fail, n_times=5)
    assert result['success'] == True  # 通过率80%，高于阈值
    assert result['is_jitter'] == True  # 不是100%通过，所以是抖动
    assert result['pass_rate'] == 0.8

def test_quick_resample():
    """测试快速版本"""
    def test():
        return True
    
    assert quick_resample(test, n_times=3) == True

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
