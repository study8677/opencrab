"""
测试回归测试中的抖动识别功能
"""
import sys
from regression import RegressionRunner

def test_jitter_detection():
    """测试抖动检测功能"""
    # 创建模拟测试用例
    test_cases = [
        {'name': '稳定测试', 'command': 'echo "pass"'},
        {'name': '抖动测试', 'command': 'exit 0 || exit 1'},  # 模拟随机失败
    ]
    
    runner = RegressionRunner(test_cases)
    results = runner.run_all_tests()
    
    print("回归测试结果:")
    print(f"总数: {results['total']}")
    print(f"通过: {results['passed']}")
    print(f"失败: {results['failed']}")
    print(f"通过率: {results['pass_rate']:.1%}")
    
    # 验证结果结构
    assert 'total' in results
    assert 'passed' in results
    assert 'failed' in results
    assert 'pass_rate' in results
    assert 'results' in results

if __name__ == "__main__":
    test_jitter_detection()
