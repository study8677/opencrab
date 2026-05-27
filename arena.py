"""
竞技场：策略 PK 裁判模块
用真实能力缺口测试两种修复策略，让数据说话。
"""

import time
import sys
import traceback
from typing import Callable, Any, Dict, List, Tuple, Optional


# ============== 原有问题函数 ==============

def original_problematic_function(numerator: int, denominator: int) -> float:
    """
    原始函数：计算分数，但分母为零时会崩溃
    这是我们的能力缺口：需要处理除零错误
    """
    # 故意不做任何防护，展示能力缺口
    return numerator / denominator


# ============== 两种策略 ==============

class ImmediateFixStrategy:
    """立即修复策略：直接修复原函数"""
    
    def name(self) -> str:
        return "立即修复"
    
    def get_solution(self) -> Callable[[int, int], float]:
        """返回修复后的函数"""
        def fixed_function(numerator: int, denominator: int) -> float:
            if denominator == 0:
                # 立即修复：返回安全值（比如0.0或无穷大）
                # 这里选择返回0.0，但添加警告
                print(f"[警告] 分母为零！numerator={numerator}, denominator=0")
                return 0.0
            return numerator / denominator
        
        return fixed_function


class BypassAlternativeStrategy:
    """绕道替代策略：不修复原函数，提供替代路径"""
    
    def name(self) -> str:
        return "绕道替代"
    
    def get_solution(self) -> Callable[[int, int], float]:
        """返回替代函数，完全绕过原问题"""
        def alternative_function(numerator: int, denominator: int) -> float:
            # 绕道替代：提供完全不同的实现
            # 可能更安全但效率稍低
            if denominator == 0:
                # 使用浮点数除法的安全处理
                return float('inf') if numerator > 0 else (
                    float('-inf') if numerator < 0 else float('nan')
                )
            return float(numerator) / float(denominator)  # 强制转为浮点
        
        return alternative_function


# ============== 测试用例生成器 ==============

def generate_test_cases() -> List[Tuple[int, int]]:
    """生成测试用例，包括正常情况和边界情况"""
    cases = []
    
    # 正常情况
    cases.extend([
        (10, 2),    # 5.0
        (-6, 3),    # -2.0
        (0, 5),     # 0.0
    ])
    
    # 边界情况：分母为零（能力缺口）
    cases.extend([
        (7, 0),     # 应该处理
        (0, 0),     # 应该处理
        (-3, 0),    # 应该处理
    ])
    
    return cases


# ============== 竞技场裁判 ==============

class Arena:
    """竞技场：让两个策略PK，用数据决定优劣"""
    
    def __init__(self):
        self.results = {}
    
    def run_pk(self, 
               strategy_a: Callable[[], Any], 
               strategy_b: Callable[[], Any],
               test_cases: List[Tuple[int, int]]) -> Dict[str, Any]:
        """
        运行PK：让两个策略在测试用例上对决
        
        Returns:
            包含详细结果的字典
        """
        print("=" * 60)
        print("竞技场开始 PK")
        print(f"测试用例数: {len(test_cases)}")
        print("=" * 60)
        
        results = {
            'strategy_a': {},
            'strategy_b': {},
            'winner': None,
            'decision_basis': []
        }
        
        # 获取两个策略的解决方案
        solution_a = strategy_a.get_solution()
        solution_b = strategy_b.get_solution()
        
        # 测试策略A
        print(f"\n测试策略A: {strategy_a.name()}")
        result_a = self._test_solution(solution_a, test_cases)
        results['strategy_a'] = {
            'name': strategy_a.name(),
            **result_a
        }
        
        # 测试策略B
        print(f"\n测试策略B: {strategy_b.name()}")
        result_b = self._test_solution(solution_b, test_cases)
        results['strategy_b'] = {
            'name': strategy_b.name(),
            **result_b
        }
        
        # 决策：选择胜者
        winner, decision_basis = self._decide_winner(results)
        results['winner'] = winner
        results['decision_basis'] = decision_basis
        
        # 打印结果
        self._print_results(results)
        
        return results
    
    def _test_solution(self, 
                      solution: Callable[[int, int], float],
                      test_cases: List[Tuple[int, int]]) -> Dict[str, Any]:
        """测试一个解决方案"""
        successes = 0
        failures = 0
        total_time = 0
        error_details = []
        
        for i, (num, den) in enumerate(test_cases):
            test_id = f"用例{i+1} ({num}/{den})"
            
            try:
                start_time = time.time()
                result = solution(num, den)
                elapsed = time.time() - start_time
                
                total_time += elapsed
                
                # 简单验证：结果应该是有限的（除特殊值外）
                if isinstance(result, (int, float)):
                    if not (result != result):  # 排除NaN
                        successes += 1
                        print(f"  ✓ {test_id}: {result:.4f} ({elapsed:.6f}秒)")
                    else:
                        failures += 1
                        error_details.append(f"{test_id}: 返回了NaN")
                        print(f"  ✗ {test_id}: 返回了NaN")
                else:
                    failures += 1
                    error_details.append(f"{test_id}: 返回了非数值类型")
                    print(f"  ✗ {test_id}: 返回了{type(result)}")
                    
            except Exception as e:
                failures += 1
                error_msg = f"{test_id}: {type(e).__name__}: {str(e)}"
                error_details.append(error_msg)
                print(f"  ✗ {test_id}: {type(e).__name__}")
                traceback.print_exc()
        
        return {
            'successes': successes,
            'failures': failures,
            'total_tests': len(test_cases),
            'success_rate': successes / len(test_cases) if test_cases else 0,
            'total_time': total_time,
            'avg_time': total_time / len(test_cases) if test_cases else 0,
            'error_details': error_details
        }
    
    def _decide_winner(self, results: Dict[str, Any]) -> Tuple[str, List[str]]:
        """
        根据验收数据决定胜者
        
        决策逻辑：
        1. 成功率优先（最高）
        2. 成功率相同时，比较平均耗时（越低越好）
        3. 都相同时，看错误严重程度
        """
        a = results['strategy_a']
        b = results['strategy_b']
        
        decision_basis = []
        
        # 1. 比较成功率
        if a['success_rate'] > b['success_rate']:
            decision_basis.append(f"成功率: A={a['success_rate']:.2%} > B={b['success_rate']:.2%}")
            return a['name'], decision_basis
        elif b['success_rate'] > a['success_rate']:
            decision_basis.append(f"成功率: B={b['success_rate']:.2%} > A={a['success_rate']:.2%}")
            return b['name'], decision_basis
        else:
            decision_basis.append(f"成功率相等: {a['success_rate']:.2%}")
        
        # 2. 成功率相同，比较平均耗时
        if a['avg_time'] < b['avg_time']:
            decision_basis.append(f"平均耗时: A={a['avg_time']:.6f}秒 < B={b['avg_time']:.6f}秒")
            return a['name'], decision_basis
        elif b['avg_time'] < a['avg_time']:
            decision_basis.append(f"平均耗时: B={b['avg_time']:.6f}秒 < A={a['avg_time']:.6f}秒")
            return b['name'], decision_basis
        else:
            decision_basis.append(f"平均耗时相等: {a['avg_time']:.6f}秒")
        
        # 3. 都相等，看错误详情（优先选择没有错误的）
        if a['failures'] == 0 and b['failures'] > 0:
            decision_basis.append("A无错误，B有错误")
            return a['name'], decision_basis
        elif b['failures'] == 0 and a['failures'] > 0:
            decision_basis.append("B无错误，A有错误")
            return b['name'], decision_basis
        
        # 4. 都相等，随机选择（实际中可以有其他规则）
        import random
        decision_basis.append("所有指标相同，随机选择")
        return random.choice([a['name'], b['name']]), decision_basis
    
    def _print_results(self, results: Dict[str, Any]):
        """打印PK结果"""
        print("\n" + "=" * 60)
        print("PK 结果汇总")
        print("=" * 60)
        
        a = results['strategy_a']
        b = results['strategy_b']
        
        print(f"策略A: {a['name']}")
        print(f"  成功率: {a['success_rate']:.2%} ({a['successes']}/{a['total_tests']})")
        print(f"  平均耗时: {a['avg_time']:.6f}秒")
        if a['error_details']:
            print(f"  错误详情: {len(a['error_details'])}个错误")
        
        print(f"\n策略B: {b['name']}")
        print(f"  成功率: {b['success_rate']:.2%} ({b['successes']}/{b['total_tests']})")
        print(f"  平均耗时: {b['avg_time']:.6f}秒")
        if b['error_details']:
            print(f"  错误详情: {len(b['error_details'])}个错误")
        
        print(f"\n🏆 胜者: {results['winner']}")
        print(f"决策依据:")
        for reason in results['decision_basis']:
            print(f"  - {reason}")
        
        print("\n" + "=" * 60)


# ============== 主程序 ==============

def main():
    """主程序：运行竞技场PK"""
    print("准备测试能力缺口：处理除零错误")
    print("能力缺口描述：original_problematic_function 在分母为零时崩溃")
    
    # 创建竞技场
    arena = Arena()
    
    # 创建两种策略
    strategy_a = ImmediateFixStrategy()
    strategy_b = BypassAlternativeStrategy()
    
    # 生成测试用例
    test_cases = generate_test_cases()
    
    # 运行PK
    results = arena.run_pk(strategy_a, strategy_b, test_cases)
    
    # 根据结果决定走哪条路
    print(f"\n最终决策：选择 '{results['winner']}' 策略")
    print("验收数据支持此决策，避免了拍脑袋决定。")
    
    return results


if __name__ == "__main__":
    main()
