"""
竞技场：进化策略 PK 裁判模块
评估近三次自改路径的优劣，量化「稳健进化」与「激进探索」的收益比。
"""

import time
import sys
import traceback
from typing import Callable, Any, Dict, List, Tuple, Optional
from dataclasses import dataclass, field


# ============== 进化路径记录 ==============

@dataclass
class EvolutionStep:
    """一次自改步骤的记录"""
    step_id: int
    style: str  # 'conservative' or 'radical'
    description: str
    risk_level: float  # 0-1
    verification_time: float  # 验证耗时(秒)
    success: bool
    improvement: float  # 改进收益 0~1
    side_effects: int = 0  # 副作用数量


@dataclass
class EvolutionPath:
    """一段进化路径(包含多次自改)"""
    name: str
    steps: List[EvolutionStep]

    @property
    def total_improvement(self) -> float:
        return sum(s.improvement for s in self.steps)

    @property
    def avg_risk(self) -> float:
        return sum(s.risk_level for s in self.steps) / len(self.steps)

    @property
    def success_rate(self) -> float:
        return sum(1 for s in self.steps if s.success) / len(self.steps)

    @property
    def total_time(self) -> float:
        return sum(s.verification_time for s in self.steps)

    @property
    def total_side_effects(self) -> int:
        return sum(s.side_effects for s in self.steps)


# ============== 两种进化风格 ==============

class ConservativeEvolution:
    """稳健进化风格：小步改动、多次验证、低风险"""

    def name(self) -> str:
        return "稳健进化"

    def describe(self) -> str:
        return "小改动、快验证、低风险、稳扎稳打"

    def generate_path(self, scenario: str) -> EvolutionPath:
        """生成稳健进化路径（模拟近三次自改）"""
        steps = []

        if scenario == "除零修复":
            steps = [
                EvolutionStep(1, "conservative", "添加 try-except 兜底", 0.1, 0.8, True, 0.6, 0),
                EvolutionStep(2, "conservative", "添加分母检查", 0.15, 1.2, True, 0.8, 0),
                EvolutionStep(3, "conservative", "添加参数验证和文档", 0.2, 1.5, True, 0.9, 0),
            ]
        elif scenario == "性能优化":
            steps = [
                EvolutionStep(1, "conservative", "添加简单缓存", 0.15, 1.0, True, 0.5, 0),
                EvolutionStep(2, "conservative", "优化热路径", 0.2, 2.0, True, 0.7, 1),
                EvolutionStep(3, "conservative", "减少冗余计算", 0.15, 1.5, True, 0.6, 0),
            ]
        elif scenario == "架构重构":
            steps = [
                EvolutionStep(1, "conservative", "抽取工具函数", 0.1, 0.5, True, 0.3, 0),
                EvolutionStep(2, "conservative", "拆分模块", 0.2, 1.8, True, 0.5, 0),
                EvolutionStep(3, "conservative", "添加接口抽象", 0.25, 2.5, True, 0.6, 0),
            ]
        else:
            steps = [
                EvolutionStep(1, "conservative", "小改动A", 0.1, 0.8, True, 0.5, 0),
                EvolutionStep(2, "conservative", "小改动B", 0.15, 1.0, True, 0.6, 0),
                EvolutionStep(3, "conservative", "小改动C", 0.2, 1.2, True, 0.7, 0),
            ]

        return EvolutionPath(self.name(), steps)


class RadicalExploration:
    """激进探索风格：大改动、快速尝试、高风险高回报"""

    def name(self) -> str:
        return "激进探索"

    def describe(self) -> str:
        return "大改动、快迭代、高风险、追求突破"

    def generate_path(self, scenario: str) -> EvolutionPath:
        """生成激进探索路径（模拟近三次自改）"""
        steps = []

        if scenario == "除零修复":
            steps = [
                EvolutionStep(1, "radical", "重写整个计算模块", 0.6, 3.0, True, 0.9, 2),
                EvolutionStep(2, "radical", "引入类型系统", 0.5, 4.0, False, 0.1, 3),
                EvolutionStep(3, "radical", "回滚并精简修复", 0.4, 2.5, True, 0.7, 1),
            ]
        elif scenario == "性能优化":
            steps = [
                EvolutionStep(1, "radical", "全异步重写", 0.7, 6.0, False, -0.2, 4),
                EvolutionStep(2, "radical", "引入 Rust 扩展", 0.8, 8.0, False, -0.5, 2),
                EvolutionStep(3, "radical", "回滚加局部缓存", 0.3, 2.0, True, 0.6, 0),
            ]
        elif scenario == "架构重构":
            steps = [
                EvolutionStep(1, "radical", "微服务拆分", 0.7, 5.0, True, 0.8, 3),
                EvolutionStep(2, "radical", "事件驱动改造", 0.6, 7.0, False, 0.0, 5),
                EvolutionStep(3, "radical", "回滚核心+保留部分改造", 0.4, 3.0, True, 0.6, 1),
            ]
        else:
            steps = [
                EvolutionStep(1, "radical", "大改动A", 0.6, 4.0, True, 0.7, 2),
                EvolutionStep(2, "radical", "大改动B", 0.7, 5.0, False, -0.3, 3),
                EvolutionStep(3, "radical", "回滚+精简", 0.4, 2.0, True, 0.5, 1),
            ]

        return EvolutionPath(self.name(), steps)


# ============== 测试场景 ==============

SCENARIOS = [
    ("除零修复", "处理 divide-by-zero 类型的能力缺口"),
    ("性能优化", "提升热路径执行效率"),
    ("架构重构", "改善代码结构和可维护性"),
]


# ============== 竞技场裁判 ==============

class Arena:
    """竞技场：让两种进化风格PK，用数据决定优劣"""

    def __init__(self):
        self.results: Dict[str, Dict[str, Any]] = {}

    def run_evaluation(self) -> Dict[str, Any]:
        """运行完整的进化策略评估"""
        print("=" * 70)
        print("竞技场：进化策略 PK 评估")
        print("评估近三次自改路径的优劣")
        print("量化「稳健进化」与「激进探索」的收益比")
        print("=" * 70)

        conservative = ConservativeEvolution()
        radical = RadicalExploration()

        scenario_results = []

        for scenario_name, scenario_desc in SCENARIOS:
            print(f"\n{'─' * 50}")
            print(f"场景: {scenario_name} - {scenario_desc}")
            print(f"{'─' * 50}")

            path_c = conservative.generate_path(scenario_name)
            path_r = radical.generate_path(scenario_name)

            comparison = self._compare_paths(path_c, path_r)
            scenario_results.append({
                'scenario': scenario_name,
                'description': scenario_desc,
                'path_conservative': path_c,
                'path_radical': path_r,
                'comparison': comparison,
            })

            self._print_scenario_result(path_c, path_r, comparison)

        # 全局汇总
        summary = self._generate_summary(scenario_results)

        return {
            'scenario_results': scenario_results,
            'summary': summary,
        }

    def _compare_paths(self, path_c: EvolutionPath, path_r: EvolutionPath) -> Dict[str, Any]:
        """对比两条进化路径"""
        # 收益/风险比
        def roi(path: EvolutionPath) -> float:
            if path.avg_risk == 0:
                return float('inf')
            return path.total_improvement / path.avg_risk

        roi_c = roi(path_c)
        roi_r = roi(path_r)

        # 稳定性
        stability_c = path_c.success_rate * (1 - path_c.total_side_effects / 15)
        stability_r = path_r.success_rate * (1 - path_r.total_side_effects / 15)

        # 综合评分（加权）
        def score(path: EvolutionPath, roi_val: float, stability: float) -> float:
            return (
                path.total_improvement * 0.3 +  # 改进收益
                roi_val * 0.3 +                  # 收益/风险比
                stability * 0.2 +                # 稳定性
                (1 / max(path.total_time, 0.1)) * 0.2  # 效率
            )

        score_c = score(path_c, roi_c, stability_c)
        score_r = score(path_r, roi_r, stability_r)

        winner = path_c.name if score_c > score_r else path_r.name

        return {
            'roi_conservative': roi_c,
            'roi_radical': roi_r,
            'stability_conservative': stability_c,
            'stability_radical': stability_r,
            'score_conservative': score_c,
            'score_radical': score_r,
            'winner': winner,
        }

    def _print_scenario_result(self, path_c: EvolutionPath, path_r: EvolutionPath,
                                comparison: Dict[str, Any]):
        """打印单个场景的对比结果"""
        print(f"\n  稳健进化 - 近三次自改:")
        for step in path_c.steps:
            status = "✓" if step.success else "✗"
            print(f"    [{status}] {step.description}: 收益={step.improvement:.2f}, 风险={step.risk_level:.1f}, 副作用={step.side_effects}")

        print(f"\n  激进探索 - 近三次自改:")
        for step in path_r.steps:
            status = "✓" if step.success else "✗"
            print(f"    [{status}] {step.description}: 收益={step.improvement:.2f}, 风险={step.risk_level:.1f}, 副作用={step.side_effects}")

        print(f"\n  对比指标:")
        print(f"    总收益:  稳健={path_c.total_improvement:.2f}  激进={path_r.total_improvement:.2f}")
        print(f"    平均风险: 稳健={path_c.avg_risk:.2f}  激进={path_r.avg_risk:.2f}")
        print(f"    收益/风险比: 稳健={comparison['roi_conservative']:.2f}  激进={comparison['roi_radical']:.2f}")
        print(f"    稳定性: 稳健={comparison['stability_conservative']:.2f}  激进={comparison['stability_radical']:.2f}")
        print(f"    综合评分: 稳健={comparison['score_conservative']:.2f}  激进={comparison['score_radical']:.2f}")
        print(f"    🏆 胜者: {comparison['winner']}")

    def _generate_summary(self, scenario_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        """生成全局汇总"""
        print("\n" + "=" * 70)
        print("全局汇总")
        print("=" * 70)

        wins_conservative = sum(1 for r in scenario_results
                                 if r['comparison']['winner'] == "稳健进化")
        wins_radical = len(scenario_results) - wins_conservative

        avg_roi_c = sum(r['comparison']['roi_conservative'] for r in scenario_results) / len(scenario_results)
        avg_roi_r = sum(r['comparison']['roi_radical'] for r in scenario_results) / len(scenario_results)

        avg_score_c = sum(r['comparison']['score_conservative'] for r in scenario_results) / len(scenario_results)
        avg_score_r = sum(r['comparison']['score_radical'] for r in scenario_results) / len(scenario_results)

        total_improvement_c = sum(r['path_conservative'].total_improvement for r in scenario_results)
        total_improvement_r = sum(r['path_radical'].total_improvement for r in scenario_results)

        total_side_effects_c = sum(r['path_conservative'].total_side_effects for r in scenario_results)
        total_side_effects_r = sum(r['path_radical'].total_side_effects for r in scenario_results)

        roi_ratio = avg_roi_r / avg_roi_c if avg_roi_c > 0 else float('inf')

        print(f"\n  场景胜率:")
        print(f"    稳健进化: {wins_conservative}/{len(scenario_results)} ({wins_conservative/len(scenario_results):.0%})")
        print(f"    激进探索: {wins_radical}/{len(scenario_results)} ({wins_radical/len(scenario_results):.0%})")

        print(f"\n  平均收益/风险比:")
        print(f"    稳健进化: {avg_roi_c:.2f}")
        print(f"    激进探索: {avg_roi_r:.2f}")
        print(f"    激进/稳健 比值: {roi_ratio:.2f}x")

        print(f"\n  平均综合评分:")
        print(f"    稳健进化: {avg_score_c:.2f}")
        print(f"    激进探索: {avg_score_r:.2f}")

        print(f"\n  总改进收益:")
        print(f"    稳健进化: {total_improvement_c:.2f}")
        print(f"    激进探索: {total_improvement_r:.2f}")

        print(f"\n  总副作用:")
        print(f"    稳健进化: {total_side_effects_c}")
        print(f"    激进探索: {total_side_effects_r}")

        # 建议
        print(f"\n  {'─' * 50}")
        print("  进化建议:")
        if wins_conservative > wins_radical:
            print("  → 当前阶段更适合「稳健进化」风格")
            print("    小步快跑、降低风险、持续积累微小改进")
        elif wins_radical > wins_conservative:
            print("  → 当前阶段可适当尝试「激进探索」风格")
            print("    但需做好回滚准备、控制副作用")
        else:
            print("  → 两种风格各有优劣，建议混合使用")
            print("    稳健为主、激进为辅，在关键节点大胆探索")

        print("=" * 70)

        return {
            'wins_conservative': wins_conservative,
            'wins_radical': wins_radical,
            'avg_roi_conservative': avg_roi_c,
            'avg_roi_radical': avg_roi_r,
            'roi_ratio': roi_ratio,
            'avg_score_conservative': avg_score_c,
            'avg_score_radical': avg_score_r,
            'total_improvement_conservative': total_improvement_c,
            'total_improvement_radical': total_improvement_r,
            'total_side_effects_conservative': total_side_effects_c,
            'total_side_effects_radical': total_side_effects_r,
            'recommendation': 'conservative' if wins_conservative > wins_radical
                              else 'radical' if wins_radical > wins_conservative
                              else 'hybrid',
        }


# ============== 主程序 ==============

def main():
    """主程序：运行进化策略PK评估"""
    print("目标：评估近三次自改路径的优劣")
    print("量化「稳健进化」与「激进探索」的收益比")
    print()

    arena = Arena()
    results = arena.run_evaluation()

    return results


if __name__ == "__main__":
    main()
