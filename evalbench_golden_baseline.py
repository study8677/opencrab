"""
evalbench_golden_baseline.py - 运行黄金任务全集，建立能力基线，找最弱3方向

用法：python -m evalbench_golden_baseline
输出：控制台报告 + baseline_report.json
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from collections import defaultdict


def load_golden_tasks():
    """加载黄金任务全集"""
    try:
        from evalbench_golden_variant import get_all_golden_tasks
        tasks = get_all_golden_tasks()
        print(f"[INFO] 从 evalbench_golden_variant 加载了 {len(tasks)} 个黄金任务")
        return tasks
    except ImportError:
        pass
    
    # fallback: 尝试从 evalbench 加载
    try:
        from evalbench import load_golden_suite
        tasks = load_golden_suite()
        print(f"[INFO] 从 evalbench 加载了 {len(tasks)} 个黄金任务")
        return tasks
    except (ImportError, AttributeError):
        pass
    
    # fallback: 内置最小黄金任务集
    print("[WARN] 使用内置最小黄金任务集")
    return _builtin_minimal_golden_tasks()


def _builtin_minimal_golden_tasks():
    """内置最小黄金任务集，覆盖主要能力维度"""
    return [
        # 代码理解
        {"id": "golden_001", "category": "code_understanding", "difficulty": "easy",
         "task": "解释这段代码的功能", "code": "def f(n): return n if n<=1 else f(n-1)+f(n-2)",
         "expected": "斐波那契数列递归"},
        
        # 代码生成
        {"id": "golden_002", "category": "code_generation", "difficulty": "medium",
         "task": "写一个函数判断素数", "expected_signature": "is_prime(n: int) -> bool"},
        
        # Bug修复
        {"id": "golden_003", "category": "bug_fix", "difficulty": "medium",
         "task": "修复bug", "buggy_code": "def avg(lst): return sum(lst)/len(lst)",
         "expected_fix": "处理空列表"},
        
        # 重构
        {"id": "golden_004", "category": "refactoring", "difficulty": "medium",
         "task": "重构为更pythonic", "code": "result=[]\nfor x in items:\n    if x>0: result.append(x*2)"},
        
        # 测试生成
        {"id": "golden_005", "category": "test_writing", "difficulty": "medium",
         "task": "为这个函数写单元测试", "code": "def add(a,b): return a+b"},
        
        # 安全分析
        {"id": "golden_006", "category": "security_analysis", "difficulty": "hard",
         "task": "找出安全漏洞", "code": "cmd = f'echo {user_input}'\nos.system(cmd)"},
        
        # 性能优化
        {"id": "golden_007", "category": "performance", "difficulty": "hard",
         "task": "优化性能", "code": "def find_dupes(lst):\n    return [x for x in lst if lst.count(x)>1]"},
        
        # API设计
        {"id": "golden_008", "category": "api_design", "difficulty": "medium",
         "task": "设计一个缓存装饰器API", "requirements": "支持TTL和maxsize"},
        
        # 错误处理
        {"id": "golden_009", "category": "error_handling", "difficulty": "medium",
         "task": "添加错误处理", "code": "f=open('data.txt')\ndata=f.read()"},
        
        # 文档编写
        {"id": "golden_010", "category": "documentation", "difficulty": "easy",
         "task": "写docstring", "code": "def merge(dict1, dict2, override=True): ..."},
        
        # 类型标注
        {"id": "golden_011", "category": "type_hints", "difficulty": "easy",
         "task": "添加类型标注", "code": "def process(items, key=None): return sorted(items, key=key)"},
        
        # 并发处理
        {"id": "golden_012", "category": "concurrency", "difficulty": "hard",
         "task": "用asyncio重写", "code": "import time\ndef fetch_all(urls):\n    return [requests.get(u) for u in urls]"},
        
        # 数据处理
        {"id": "golden_013", "category": "data_processing", "difficulty": "medium",
         "task": "解析CSV计算平均值", "csv_sample": "name,score\nAlice,85\nBob,92"},
        
        # 正则表达式
        {"id": "golden_014", "category": "regex", "difficulty": "medium",
         "task": "写正则匹配邮箱", "expected_pattern": r"[^@]+@[^@]+\.[^@]+"},
        
        # 算法
        {"id": "golden_015", "category": "algorithm", "difficulty": "hard",
         "task": "实现二叉树层序遍历", "complexity": "O(n)"},
    ]


def run_evaluation(tasks):
    """运行评估，返回每个任务的分数和详情"""
    results = []
    eval_engine = _get_eval_engine()
    
    total = len(tasks)
    for i, task in enumerate(tasks):
        task_id = task.get('id', f'task_{i}')
        category = task.get('category', 'unknown')
        difficulty = task.get('difficulty', 'medium')
        
        print(f"\r[{i+1}/{total}] 评估中: {task_id} ({category})", end="", flush=True)
        
        try:
            result = eval_engine(task)
            results.append({
                "task_id": task_id,
                "category": category,
                "difficulty": difficulty,
                "score": result.get("score", 0),
                "details": result.get("details", {}),
                "passed": result.get("score", 0) >= 0.6,
                "time_ms": result.get("time_ms", 0)
            })
        except Exception as e:
            results.append({
                "task_id": task_id,
                "category": category,
                "difficulty": difficulty,
                "score": 0,
                "details": {"error": str(e)},
                "passed": False,
                "time_ms": 0
            })
    
    print()  # 换行
    return results


def _get_eval_engine():
    """获取评估引擎"""
    # 尝试使用 evalbench 的评分器
    try:
        from evalbench import GoldenEvaluator
        evaluator = GoldenEvaluator()
        return evaluator.evaluate_task
    except (ImportError, AttributeError):
        pass
    
    # 尝试使用内置评分
    try:
        from evalbench import score_task
        return score_task
    except (ImportError, AttributeError):
        pass
    
    # fallback: 使用简单启发式评分
    print("[WARN] 使用简单启发式评分器")
    return _heuristic_scorer


def _heuristic_scorer(task):
    """简单启发式评分器（用于无eval engine时）"""
    import time
    start = time.time()
    
    # 基于任务类型的简单评分逻辑
    category = task.get('category', 'unknown')
    difficulty = task.get('difficulty', 'medium')
    
    # 模拟评估 - 实际应该调用真正的AI评估
    base_score = 0.7  # 基础分
    
    # 难度调整
    diff_mult = {"easy": 1.1, "medium": 1.0, "hard": 0.85}
    score = min(1.0, base_score * diff_mult.get(difficulty, 1.0))
    
    # 添加一些变化
    import random
    random.seed(hash(task.get('id', '')))
    score += random.uniform(-0.15, 0.15)
    score = max(0, min(1, score))
    
    elapsed = int((time.time() - start) * 1000)
    
    return {
        "score": round(score, 3),
        "details": {"method": "heuristic", "note": "请用真正的eval engine替换"},
        "time_ms": elapsed
    }


def analyze_results(results):
    """分析结果，找出最弱的3个能力方向"""
    
    # 按类别分组统计
    category_stats = defaultdict(lambda: {
        "scores": [],
        "count": 0,
        "passed": 0,
        "total_time_ms": 0
    })
    
    for r in results:
        cat = r["category"]
        stats = category_stats[cat]
        stats["scores"].append(r["score"])
        stats["count"] += 1
        if r["passed"]:
            stats["passed"] += 1
        stats["total_time_ms"] += r.get("time_ms", 0)
    
    # 计算每个类别的统计指标
    category_analysis = {}
    for cat, stats in category_stats.items():
        scores = stats["scores"]
        avg_score = sum(scores) / len(scores) if scores else 0
        pass_rate = stats["passed"] / stats["count"] if stats["count"] > 0 else 0
        min_score = min(scores) if scores else 0
        max_score = max(scores) if scores else 0
        variance = sum((s - avg_score)**2 for s in scores) / len(scores) if scores else 0
        
        category_analysis[cat] = {
            "average_score": round(avg_score, 3),
            "pass_rate": round(pass_rate, 3),
            "min_score": round(min_score, 3),
            "max_score": round(max_score, 3),
            "variance": round(variance, 4),
            "task_count": stats["count"],
            "total_time_ms": stats["total_time_ms"]
        }
    
    # 找出最弱的3个（按平均分排序）
    sorted_categories = sorted(
        category_analysis.items(),
        key=lambda x: x[1]["average_score"]
    )
    weakest_3 = sorted_categories[:3]
    
    # 找出最强的3个
    strongest_3 = sorted_categories[-3:]
    
    # 全局统计
    all_scores = [r["score"] for r in results]
    global_avg = sum(all_scores) / len(all_scores) if all_scores else 0
    global_pass = sum(1 for r in results if r["passed"]) / len(results) if results else 0
    
    return {
        "category_analysis": category_analysis,
        "weakest_3": [{"category": c, **s} for c, s in weakest_3],
        "strongest_3": [{"category": c, **s} for c, s in strongest_3],
        "global": {
            "average_score": round(global_avg, 3),
            "pass_rate": round(global_pass, 3),
            "total_tasks": len(results),
            "total_passed": sum(1 for r in results if r["passed"]),
            "total_time_ms": sum(r.get("time_ms", 0) for r in results)
        }
    }


def print_report(analysis):
    """打印可读报告"""
    print("\n" + "="*70)
    print("  EVALBENCH 黄金任务基线报告")
    print("  " + datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("="*70)
    
    # 全局统计
    g = analysis["global"]
    print(f"\n【全局统计】")
    print(f"  总任务数: {g['total_tasks']}")
    print(f"  通过数:   {g['total_passed']}")
    print(f"  通过率:   {g['pass_rate']*100:.1f}%")
    print(f"  平均分:   {g['average_score']:.3f}")
    print(f"  总耗时:   {g['total_time_ms']/1000:.1f}s")
    
    # 各能力方向详情
    print(f"\n【各能力方向得分】")
    print(f"  {'能力方向':<25} {'平均分':>8} {'通过率':>8} {'任务数':>6}")
    print(f"  {'-'*25} {'-'*8} {'-'*8} {'-'*6}")
    
    for cat, stats in sorted(analysis["category_analysis"].items(), 
                              key=lambda x: x[1]["average_score"]):
        print(f"  {cat:<25} {stats['average_score']:>8.3f} {stats['pass_rate']*100:>7.1f}% {stats['task_count']:>6}")
    
    # 最弱3个方向 - 需要重点进化
    print(f"\n{'='*70}")
    print(f"  🎯 最弱的3个能力方向（下一阶段进化靶心）")
    print(f"{'='*70}")
    
    for i, item in enumerate(analysis["weakest_3"], 1):
        cat = item["category"]
        stats = item
        print(f"\n  【{i}】{cat}")
        print(f"      平均分: {stats['average_score']:.3f} (通过率: {stats['pass_rate']*100:.1f}%)")
        print(f"      分数范围: [{stats['min_score']:.3f}, {stats['max_score']:.3f}]")
        print(f"      方差: {stats['variance']:.4f} {'(不稳定)' if stats['variance'] > 0.04 else '(稳定)'}")
        print(f"      任务数: {stats['task_count']}")
        print(f"      → 建议: 专项突破，增加该方向的训练任务")
    
    # 最强3个方向 - 保持优势
    print(f"\n{'='*70}")
    print(f"  💪 最强的3个能力方向（保持优势）")
    print(f"{'='*70}")
    
    for i, item in enumerate(analysis["strongest_3"], 1):
        cat = item["category"]
        stats = item
        print(f"  {i}. {cat}: {stats['average_score']:.3f} (通过率: {stats['pass_rate']*100:.1f}%)")
    
    print(f"\n{'='*70}")
    print("  报告已保存到: baseline_report.json")
    print("="*70)


def save_report(analysis, results):
    """保存报告到JSON"""
    report = {
        "timestamp": datetime.now().isoformat(),
        "analysis": analysis,
        "raw_results": results
    }
    
    with open("baseline_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)
    
    print(f"\n[INFO] 原始结果已保存到 baseline_report.json")


def generate_evolution_targets(analysis):
    """生成下一阶段进化目标"""
    targets = []
    
    for i, item in enumerate(analysis["weakest_3"], 1):
        cat = item["category"]
        avg = item["average_score"]
        
        target = {
            "priority": i,
            "category": cat,
            "current_score": avg,
            "target_score": round(min(1.0, avg + 0.2), 3),  # 目标提升0.2
            "improvement_needed": round(0.2, 3),
            "suggested_actions": _get_suggested_actions(cat, avg)
        }
        targets.append(target)
    
    return targets


def _get_suggested_actions(category, current_score):
    """根据类别和分数给出建议"""
    suggestions = {
        "code_understanding": [
            "增加代码阅读练习",
            "实现ast解析加深理解",
            "添加readpack模块使用"
        ],
        "code_generation": [
            "增加生成任务的测试用例",
            "实现渐进式生成",
            "添加生成结果验证"
        ],
        "bug_fix": [
            "建立常见bug模式库",
            "实现autopsy模块深度分析",
            "增加回归测试覆盖"
        ],
        "refactoring": [
            "学习更多重构模式",
            "实现AST级别的重构",
            "添加重构前后对比验证"
        ],
        "test_writing": [
            "学习测试设计模式",
            "实现自动生成测试",
            "增加边界条件覆盖"
        ],
        "security_analysis": [
            "学习常见漏洞模式",
            "实现代码扫描",
            "添加安全规则库"
        ],
        "performance": [
            "学习性能分析工具",
            "实现性能profiling",
            "添加基准测试"
        ],
        "api_design": [
            "学习API设计原则",
            "实现接口一致性检查",
            "添加向后兼容验证"
        ],
        "error_handling": [
            "建立异常处理模式",
            "实现错误恢复机制",
            "添加边界条件测试"
        ],
        "documentation": [
            "学习文档最佳实践",
            "实现自动文档生成",
            "添加文档质量检查"
        ],
        "type_hints": [
            "学习类型系统",
            "实现类型检查",
            "添加类型推断"
        ],
        "concurrency": [
            "学习并发模式",
            "实现async/await",
            "添加并发测试"
        ],
        "data_processing": [
            "学习数据处理库",
            "实现流式处理",
            "添加大数据测试"
        ],
        "regex": [
            "学习正则表达式",
            "实现正则测试",
            "添加复杂模式"
        ],
        "algorithm": [
            "学习算法设计",
            "实现算法验证",
            "添加复杂度分析"
        ]
    }
    
    return suggestions.get(category, [f"专项研究{category}", "增加练习任务", "实现评估验证"])


def main():
    """主函数"""
    print("\n" + "="*70)
    print("  开始运行 EVALBENCH 黄金任务全集")
    print("="*70)
    
    start_time = time.time()
    
    # 1. 加载任务
    print("\n[1/4] 加载黄金任务...")
    tasks = load_golden_tasks()
    
    # 2. 运行评估
    print("\n[2/4] 运行评估...")
    results = run_evaluation(tasks)
    
    # 3. 分析结果
    print("\n[3/4] 分析结果...")
    analysis = analyze_results(results)
    
    # 4. 生成报告
    print("\n[4/4] 生成报告...")
    print_report(analysis)
    save_report(analysis, results)
    
    # 5. 生成进化目标
    targets = generate_evolution_targets(analysis)
    print(f"\n【下一阶段进化目标】")
    for t in targets:
        print(f"  {t['priority']}. {t['category']}: {t['current_score']:.3f} → {t['target_score']:.3f}")
    
    # 保存进化目标
    with open("evolution_targets.json", "w", encoding="utf-8") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(),
            "baseline_score": analysis["global"]["average_score"],
            "targets": targets
        }, f, indent=2, ensure_ascii=False)
    
    elapsed = time.time() - start_time
    print(f"\n[完成] 总耗时: {elapsed:.1f}s")
    
    # 返回最弱3个方向供后续使用
    return analysis["weakest_3"]


if __name__ == "__main__":
    weakest = main()
    sys.exit(0)
