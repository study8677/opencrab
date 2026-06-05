"""
run_fitness_baseline.py - 真适应度基线评测

串联 arena + boundaryeval + regression + canary 四维评测，
将结果写入 git 跟踪的 evidence/baseline/ 证据账本，
为后续多拍定向训练提供可证伪对照刻度。

Usage:
    python run_fitness_baseline.py
    python run_fitness_baseline.py --quick      # 仅 smoke 级别
    python run_fitness_baseline.py --modules MOD1 MOD2  # 指定模块
"""

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Optional

# 基础路径
REPO_ROOT = Path(__file__).parent
EVIDENCE_DIR = REPO_ROOT / "evidence" / "baseline"
EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class BaselineResult:
    """单次基线评测结果"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    duration_seconds: float = 0.0
    arena_passed: int = 0
    arena_failed: int = 0
    arena_total: int = 0
    boundary_passed: int = 0
    boundary_failed: int = 0
    boundary_total: int = 0
    regression_passed: int = 0
    regression_failed: int = 0
    regression_total: int = 0
    canary_passed: int = 0
    canary_failed: int = 0
    canary_total: int = 0
    errors: list = field(default_factory=list)

    @property
    def total_passed(self) -> int:
        return self.arena_passed + self.boundary_passed + self.regression_passed + self.canary_passed

    @property
    def total_failed(self) -> int:
        return self.arena_failed + self.boundary_failed + self.regression_failed + self.canary_failed

    @property
    def total_tests(self) -> int:
        return self.arena_total + self.boundary_total + self.regression_total + self.canary_total

    @property
    def pass_rate(self) -> float:
        if self.total_tests == 0:
            return 0.0
        return self.total_passed / self.total_tests

    @property
    def canary_pass_rate(self) -> float:
        if self.canary_total == 0:
            return 0.0
        return self.canary_passed / self.canary_total

    def summary(self) -> str:
        return (
            f"基线评测 [{self.timestamp}]\n"
            f"  耗时: {self.duration_seconds:.1f}s\n"
            f"  总计: {self.total_tests} | 通过: {self.total_passed} | 失败: {self.total_failed}\n"
            f"  通过率: {self.pass_rate:.1%}\n"
            f"  ─ arena:      {self.arena_passed}/{self.arena_total}\n"
            f"  ─ boundary:   {self.boundary_passed}/{self.boundary_total}\n"
            f"  ─ regression: {self.regression_passed}/{self.regression_total}\n"
            f"  ─ canary:     {self.canary_passed}/{self.canary_total} ({self.canary_pass_rate:.1%})\n"
            + (f"  ⚠ 错误: {len(self.errors)}\n" if self.errors else "")
        )


def run_arena(args) -> tuple[int, int, int]:
    """运行 arena 评测"""
    try:
        from arena import Arena
        arena = Arena(quick=args.quick)
        result = arena.run()
        return result.get("passed", 0), result.get("failed", 0), result.get("total", 0)
    except Exception as e:
        print(f"  ⚠ arena 失败: {e}")
        traceback.print_exc()
        return 0, 0, 0


def run_boundaryeval(args) -> tuple[int, int, int]:
    """运行 boundaryeval 评测"""
    try:
        from boundaryeval import BoundaryEval
        be = BoundaryEval(quick=args.quick)
        result = be.run()
        return result.get("passed", 0), result.get("failed", 0), result.get("total", 0)
    except Exception as e:
        print(f"  ⚠ boundaryeval 失败: {e}")
        traceback.print_exc()
        return 0, 0, 0


def run_regression(args) -> tuple[int, int, int]:
    """运行 regression 评测"""
    try:
        from regression import RegressionSuite
        suite = RegressionSuite(quick=args.quick, modules=args.modules)
        result = suite.run()
        return result.get("passed", 0), result.get("failed", 0), result.get("total", 0)
    except Exception as e:
        print(f"  ⚠ regression 失败: {e}")
        traceback.print_exc()
        return 0, 0, 0


def run_canary(args) -> tuple[int, int, int]:
    """运行 canary 评测"""
    try:
        from canary import Canary
        canary = Canary(quick=args.quick)
        result = canary.run()
        return result.get("passed", 0), result.get("failed", 0), result.get("total", 0)
    except Exception as e:
        print(f"  ⚠ canary 失败: {e}")
        traceback.print_exc()
        return 0, 0, 0


def save_baseline(result: BaselineResult, label: str = "current") -> Path:
    """保存基线结果到 evidence/ 目录"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"baseline_{label}_{timestamp}.json"
    filepath = EVIDENCE_DIR / filename

    data = asdict(result)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 同时更新 latest.json 作为快速引用
    latest_path = EVIDENCE_DIR / "latest.json"
    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    # 更新 index.json 追踪所有基线记录
    index_path = EVIDENCE_DIR / "index.json"
    if index_path.exists():
        with open(index_path) as f:
            index = json.load(f)
    else:
        index = {"baselines": []}

    index["baselines"].append({
        "timestamp": result.timestamp,
        "label": label,
        "filename": filename,
        "pass_rate": result.pass_rate,
        "total_tests": result.total_tests
    })
    with open(index_path, "w", encoding="utf-8") as f:
        json.dump(index, f, indent=2, ensure_ascii=False)

    return filepath


def generate_report(result: BaselineResult) -> str:
    """生成 Markdown 格式的基线报告"""
    badge = "🟢" if result.pass_rate >= 0.9 else ("🟡" if result.pass_rate >= 0.7 else "🔴")
    canary_badge = "🟢" if result.canary_pass_rate >= 0.75 else ("🟡" if result.canary_pass_rate >= 0.5 else "🔴")

    report = f"""# 真适应度基线报告

**生成时间**: {result.timestamp}  
**通过率**: {badge} {result.pass_rate:.1%}
**Canary 通过率**: {canary_badge} {result.canary_pass_rate:.1%} (基准 75%)

## 评测汇总

| 维度 | 通过 | 失败 | 总计 | 通过率 |
|------|------|------|------|--------|
| Arena | {result.arena_passed} | {result.arena_failed} | {result.arena_total} | {result.arena_passed/max(result.arena_total,1):.1%} |
| BoundaryEval | {result.boundary_passed} | {result.boundary_failed} | {result.boundary_total} | {result.boundary_passed/max(result.boundary_total,1):.1%} |
| Regression | {result.regression_passed} | {result.regression_failed} | {result.regression_total} | {result.regression_passed/max(result.regression_total,1):.1%} |
| Canary | {result.canary_passed} | {result.canary_failed} | {result.canary_total} | {result.canary_pass_rate:.1%} |
| **总计** | **{result.total_passed}** | **{result.total_failed}** | **{result.total_tests}** | **{result.pass_rate:.1%}** |

## Canary 基准检查

- **基准线**: 75%
- **当前**: {result.canary_pass_rate:.1%}
- **状态**: {"✅ 达标" if result.canary_pass_rate >= 0.75 else "❌ 未达标"}

## 错误详情

"""
    if result.errors:
        for i, err in enumerate(result.errors, 1):
            report += f"{i}. `{err['source']}`: {err['message']}\n"
    else:
        report += "_无错误_\n"

    report += f"""
## 用途说明

此基线为真适应度能力的**客观刻度**，而非产物堆叠计数。
后续每一拍的改动都应对照此基线，证明：
- 能力真实提升（通过率↑ 或 能力维度扩展）
- 而非假性瘦身（删除代码、降低覆盖、虚报通过）

---
_运行耗时: {result.duration_seconds:.1f}s_
"""
    return report


def save_state_md(result: BaselineResult) -> Optional[Path]:
    """保存简明结果到 state/projects/fitness-baseline.md（供 git 追踪和复算）"""
    state_dir = REPO_ROOT / "state" / "projects"
    state_dir.mkdir(parents=True, exist_ok=True)
    md_path = state_dir / "fitness-baseline.md"

    badge = "🟢" if result.pass_rate >= 0.9 else ("🟡" if result.pass_rate >= 0.7 else "🔴")
    canary_badge = "🟢" if result.canary_pass_rate >= 0.75 else ("🟡" if result.canary_pass_rate >= 0.5 else "🔴")
    canary_status = "✅ 达标" if result.canary_pass_rate >= 0.75 else "❌ 未达标"

    content = f"""# Fitness Baseline — 可复算真锚

> **本文件由 run_fitness_baseline.py 自动生成，git 跟踪，任何「我又进步了」需对照此文件验证。**

## 最新基线

| 字段 | 值 |
|------|-----|
| 时间戳 | `{result.timestamp}` |
| 耗时 | {result.duration_seconds:.1f}s |
| 通过率 | {badge} {result.pass_rate:.1%} |
| Canary | {canary_badge} {result.canary_pass_rate:.1%} ({canary_status}, 基准 75%) |

## 各维度详情

| 维度 | 通过 | 失败 | 总计 | 通过率 |
|------|------|------|------|--------|
| arena | {result.arena_passed} | {result.arena_failed} | {result.arena_total} | {result.arena_passed/max(result.arena_total,1):.1%} |
| boundaryeval | {result.boundary_passed} | {result.boundary_failed} | {result.boundary_total} | {result.boundary_passed/max(result.boundary_total,1):.1%} |
| regression | {result.regression_passed} | {result.regression_failed} | {result.regression_total} | {result.regression_passed/max(result.regression_total,1):.1%} |
| canary | {result.canary_passed} | {result.canary_failed} | {result.canary_total} | {result.canary_pass_rate:.1%} |

## Canary 基准检查

| 检查项 | 基准 | 当前 | 状态 |
|--------|------|------|------|
| Canary 通过率 | 75% | {result.canary_pass_rate:.1%} | {canary_status} |

## 数值快照（机器可读）

```json
{{
  "timestamp": "{result.timestamp}",
  "pass_rate": {result.pass_rate},
  "canary_pass_rate": {result.canary_pass_rate},
  "total_passed": {result.total_passed},
  "total_failed": {result.total_failed},
  "total_tests": {result.total_tests},
  "duration_seconds": {result.duration_seconds},
  "arena": {{"passed": {result.arena_passed}, "failed": {result.arena_failed}, "total": {result.arena_total}}},
  "boundaryeval": {{"passed": {result.boundary_passed}, "failed": {result.boundary_failed}, "total": {result.boundary_total}}},
  "regression": {{"passed": {result.regression_passed}, "failed": {result.regression_failed}, "total": {result.regression_total}}},
  "canary": {{"passed": {result.canary_passed}, "failed": {result.canary_failed}, "total": {result.canary_total}}}
}}
```

## 复算命令

```bash
cd {REPO_ROOT}
python run_fitness_baseline.py --output-md  # 重跑并更新本文件
```
"""
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(content)
    return md_path


def main():
    parser = argparse.ArgumentParser(description="真适应度基线评测")
    parser.add_argument("--quick", action="store_true", help="快速 smoke 级别评测")
    parser.add_argument("--modules", nargs="*", help="指定 regression 测试的模块")
    parser.add_argument("--label", default="current", help="基线标签 (用于文件名)")
    parser.add_argument("--output-md", action="store_true", help="同时写入 state/projects/fitness-baseline.md")
    parser.add_argument("--canary-only", action="store_true", help="仅运行 canary 评测")
    args = parser.parse_args()

    print("=" * 60)
    print("真适应度基线评测")
    print(f"模式: {'快速 smoke' if args.quick else '完整评测'}")
    if args.canary_only:
        print("范围: 仅 canary")
    if args.modules:
        print(f"模块: {', '.join(args.modules)}")
    print("=" * 60)

    result = BaselineResult()
    start_time = time.time()

    if args.canary_only:
        # 仅运行 canary
        print("\n[仅 Canary] 运行 Canary 评测...")
        canary_passed, canary_failed, canary_total = run_canary(args)
        result.canary_passed = canary_passed
        result.canary_failed = canary_failed
        result.canary_total = canary_total
        print(f"      Canary: {canary_passed}/{canary_total} 通过 ({result.canary_pass_rate:.1%})")
    else:
        # 1. Arena 评测
        print("\n[1/4] 运行 Arena 评测...")
        arena_passed, arena_failed, arena_total = run_arena(args)
        result.arena_passed = arena_passed
        result.arena_failed = arena_failed
        result.arena_total = arena_total
        print(f"      Arena: {arena_passed}/{arena_total} 通过")

        # 2. BoundaryEval 评测
        print("\n[2/4] 运行 BoundaryEval 评测...")
        boundary_passed, boundary_failed, boundary_total = run_boundaryeval(args)
        result.boundary_passed = boundary_passed
        result.boundary_failed = boundary_failed
        result.boundary_total = boundary_total
        print(f"      BoundaryEval: {boundary_passed}/{boundary_total} 通过")

        # 3. Regression 评测
        print("\n[3/4] 运行 Regression 评测...")
        reg_passed, reg_failed, reg_total = run_regression(args)
        result.regression_passed = reg_passed
        result.regression_failed = reg_failed
        result.regression_total = reg_total
        print(f"      Regression: {reg_passed}/{reg_total} 通过")

        # 4. Canary 评测
        print("\n[4/4] 运行 Canary 评测...")
        canary_passed, canary_failed, canary_total = run_canary(args)
        result.canary_passed = canary_passed
        result.canary_failed = canary_failed
        result.canary_total = canary_total
        print(f"      Canary: {canary_passed}/{canary_total} 通过 ({result.canary_pass_rate:.1%})")

    # 计算耗时
    result.duration_seconds = time.time() - start_time

    # Canary 基准检查
    print("\n" + "=" * 60)
    print(f"📊 Canary 基准检查")
    print(f"   基准: 75%")
    print(f"   当前: {result.canary_pass_rate:.1%}")
    if result.canary_pass_rate >= 0.75:
        print(f"   状态: ✅ 达标 - 可焊 fitness.json 并回灌 evidence")
    else:
        print(f"   状态: ❌ 未达标 - 需尸检根因")
    print("=" * 60)

    # 保存结果
    print("\n保存基线证据...")
    filepath = save_baseline(result, args.label)
    print(f"  → {filepath}")

    # 生成报告
    report = generate_report(result)
    report_path = EVIDENCE_DIR / f"report_{args.label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"  → {report_path}")

    # 可选：写入 state/projects/fitness-baseline.md（供 git 追踪真锚）
    if args.output_md:
        md_path = save_state_md(result)
        print(f"  → {md_path} (git 可追踪的真锚)")

    # 输出摘要
    print("\n" + "=" * 60)
    print(result.summary())
    print("=" * 60)

    # Git 提示
    print("\n💡 提示: 运行以下命令将基线证据加入 git 跟踪:")
    print(f"   git add {EVIDENCE_DIR.relative_to(REPO_ROOT)}")
    print(f"   git diff --cached --stat")

    return 0 if result.total_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
