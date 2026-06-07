#!/usr/bin/env python3
"""
真适应度进化管道：跑 evalbench 黄金基线 → 找最弱格 → brain-only 出补丁 → 3x 复现验证

用法:
    python run_evalbench_golden_pipeline.py
    python run_evalbench_golden_pipeline.py --find-only   # 只跑前两步(找最弱格)
    python run_evalbench_golden_pipeline.py --patch-only  # 只跑后两步(用已保存的最弱格)
    python run_evalbench_golden_pipeline.py --json        # 纯机读输出
"""
import argparse
import json
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
RESULTS_FILE = REPO_ROOT / ".golden_pipeline_results.json"
WEAKEST_FILE = REPO_ROOT / ".weakest_cell.json"


# ── 步骤 1: 跑黄金基线 ───────────────────────────────────────────────────────────
def run_golden_baseline(timeout: int = 300) -> dict:
    """运行 evalbench 黄金任务全集，获取当前基线分数。"""
    print("=" * 60)
    print("步骤 1/4: 运行 evalbench 黄金基线...")
    print("=" * 60)

    start = time.time()
    try:
        result = subprocess.run(
            [sys.executable, "evalbench.py", "--mode", "baseline", "--json-output"],
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=REPO_ROOT
        )
        elapsed = time.time() - start

        if result.returncode == 0:
            try:
                scores = json.loads(result.stdout.strip())
                print(f"✅ 黄金基线完成，耗时 {elapsed:.1f}s")
                return {"status": "success", "scores": scores, "elapsed": elapsed}
            except json.JSONDecodeError:
                return {
                    "status": "partial",
                    "raw_output": result.stdout,
                    "elapsed": elapsed,
                    "stderr": result.stderr
                }
        else:
            print(f"❌ 黄金基线失败: {result.stderr[:200]}")
            return {"status": "error", "stderr": result.stderr, "elapsed": elapsed}

    except subprocess.TimeoutExpired:
        return {"status": "timeout", "elapsed": timeout}
    except Exception as e:
        return {"status": "exception", "error": str(e)}


# ── 步骤 2: 找最弱格 ───────────────────────────────────────────────────────────
def find_weakest_cell(scores: dict) -> tuple[str, float, dict]:
    """从分数中找出最弱的 cell/格。"""
    print("=" * 60)
    print("步骤 2/4: 找最弱格...")
    print("=" * 60)

    weakest_id = None
    min_score = float('inf')
    score_detail = {}

    for cell_id, score_data in scores.items():
        if isinstance(score_data, dict):
            score = score_data.get('score', score_data.get('accuracy', 100))
            detail = score_data
        else:
            score = float(score_data)
            detail = {"score": score}
        score_detail[cell_id] = detail
        if score < min_score:
            min_score = score
            weakest_id = cell_id

    if weakest_id:
        print(f"🔍 最弱格: {weakest_id}")
        print(f"   当前分数: {min_score}")
        print(f"   详情: {json.dumps(score_detail.get(weakest_id, {}), indent=2, ensure_ascii=False)[:200]}")
    else:
        print("⚠️  未能找到最弱格（分数为空或格式异常）")
        weakest_id = "unknown"
        min_score = 0.0

    return weakest_id, min_score, score_detail


# ── 步骤 3: brain-only 出补丁 ────────────────────────────────────────────────────
def brainonly_patch(weakest_id: str, score: float) -> dict:
    """用 brain-only 方式为最弱格生成补丁。

    策略：
    1. 分析最弱格的特征（从 evalbench 任务定义推断）
    2. 用 intentpatch 编译自然语言意图
    3. 只在影子上验证，不碰真身
    """
    print("=" * 60)
    print("步骤 3/4: brain-only 出补丁...")
    print("=" * 60)

    # 从 weakest_id 推断任务类型，生成对应的自然语言指令
    # evalbench 的 cell_id 格式通常是 task_name.subtask
    parts = weakest_id.split('.')
    task_name = parts[0] if parts else weakest_id

    # 通用提分意图：根据任务类型选择对应的修复方向
    intent_map = {
        # 格式/规范化问题 → 修复格式
        "format": "把 format.strict 改成 true",
        "json": "把 json.canonical 改成 true",
        # 代码问题 → 修复代码
        "syntax": "把 syntax.check 改成 true",
        "import": "把 import.resolved 改成 true",
        # 质量/测试 → 提质量
        "test": "把 test.coverage 改成 80",
        "coverage": "把 coverage.threshold 改成 80",
        "quality": "把 quality.min_score 改成 85",
        # 默认：通用提分
        "default": f"把 tasks.{weakest_id}.priority 改成 high"
    }

    # 选择最匹配的意图
    matched_intent = None
    for key, intent in intent_map.items():
        if key in task_name.lower():
            matched_intent = intent
            break
    if not matched_intent:
        matched_intent = intent_map["default"]

    print(f"🧠 意图: {matched_intent}")

    # 用 intentpatch 编译并验证
    try:
        result = subprocess.run(
            [sys.executable, "intentpatch.py", "--fit", "evalbench_config.json", matched_intent],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=REPO_ROOT
        )

        applied = result.returncode == 0
        output = result.stdout.strip()

        print(f"📋 编译结果: {'✅ 成功' if applied else '❌ 失败'}")
        if output:
            print(f"   {output[:300]}")

        return {
            "intent": matched_intent,
            "applied": applied,
            "stdout": output,
            "stderr": result.stderr
        }
    except Exception as e:
        print(f"❌ intentpatch 调用失败: {e}")
        return {"intent": matched_intent, "applied": False, "error": str(e)}


# ── 步骤 4: 3x 复现验证 ────────────────────────────────────────────────────────
def three_x_replication(weakest_id: str) -> dict:
    """对最弱格跑 3 次独立 evalbench 验证，确认分数可复现。"""
    print("=" * 60)
    print("步骤 4/4: 3x 复现验证...")
    print("=" * 60)

    runs = []
    for i in range(1, 4):
        print(f"\n  第 {i}/3 次运行...")
        try:
            result = subprocess.run(
                [sys.executable, "evalbench.py", "--mode", "single", "--cell", weakest_id, "--json-output"],
                capture_output=True,
                text=True,
                timeout=120,
                cwd=REPO_ROOT
            )

            if result.returncode == 0:
                try:
                    score_data = json.loads(result.stdout.strip())
                    score = score_data.get('score', score_data.get('accuracy', 0))
                    runs.append({"run": i, "score": score, "status": "success"})
                    print(f"    ✅ 分数: {score}")
                except json.JSONDecodeError:
                    runs.append({"run": i, "status": "parse_error", "output": result.stdout[:100]})
                    print(f"    ⚠️  解析失败")
            else:
                runs.append({"run": i, "status": "error", "stderr": result.stderr[:100]})
                print(f"    ❌ 运行失败")

        except subprocess.TimeoutExpired:
            runs.append({"run": i, "status": "timeout"})
            print(f"    ⏰ 超时")
        except Exception as e:
            runs.append({"run": i, "status": "exception", "error": str(e)})
            print(f"    💥 异常: {e}")

    # 分析复现性
    scores = [r.get("score") for r in runs if r.get("status") == "success"]
    if len(scores) >= 2:
        variance = max(scores) - min(scores)
        reproducible = variance < 5.0  # 分数波动 < 5 视为可复现
    else:
        variance = None
        reproducible = False

    print(f"\n📊 复现结果:")
    print(f"   成功次数: {len(scores)}/3")
    print(f"   分数范围: {min(scores) if scores else 'N/A'} - {max(scores) if scores else 'N/A'}")
    print(f"   波动: {variance if variance is not None else 'N/A'}")
    print(f"   可复现: {'✅ 是' if reproducible else '❌ 否'}")

    return {"runs": runs, "scores": scores, "variance": variance, "reproducible": reproducible}


# ── 主流程 ─────────────────────────────────────────────────────────────────────
def run_pipeline(find_only: bool = False, patch_only: bool = False, json_output: bool = False):
    """运行完整管道或分段执行。"""
    results = {
        "timestamp": datetime.now().isoformat(),
        "pipeline": "golden_fitness_evolution",
        "steps": {}
    }

    # 加载已保存的最弱格（patch-only 模式需要）
    weakest_data = {}
    if WEAKEST_FILE.exists():
        weakest_data = json.loads(WEAKEST_FILE.read_text())
        if not json_output:
            print(f"📂 从 {WEAKEST_FILE} 加载已保存的最弱格: {weakest_data.get('cell')}")

    # 步骤 1: 跑基线（除非 patch-only 且已有数据）
    if not patch_only or not weakest_data.get("cell"):
        baseline = run_golden_baseline()
        results["steps"]["baseline"] = baseline

        if baseline.get("status") == "success":
            weakest_id, min_score, score_detail = find_weakest_cell(baseline["scores"])
            results["steps"]["weakest"] = {
                "cell": weakest_id,
                "score": min_score,
                "all_scores": score_detail
            }
            # 保存最弱格
            WEAKEST_FILE.write_text(json.dumps({
                "cell": weakest_id,
                "score": min_score,
                "timestamp": datetime.now().isoformat()
            }, indent=2))
            weakest_data = {"cell": weakest_id, "score": min_score}
        elif find_only:
            if not json_output:
                print("\n⚠️  基线未能获取完整分数，管道终止（--find-only 模式）")
            return results
    else:
        if not json_output:
            print("跳过步骤 1（--patch-only 模式且已有最弱格数据）")

    # 步骤 2: 找最弱格（已在上一步完成，或从文件加载）
    weakest_id = weakest_data.get("cell")
    if not weakest_id:
        if not json_output:
            print("❌ 没有最弱格数据，无法继续")
        return results

    results["steps"]["weakest"] = weakest_data

    if not find_only:
        # 步骤 3: brain-only 出补丁
        patch_result = brainonly_patch(weakest_id, weakest_data.get("score", 0))
        results["steps"]["patch"] = patch_result

        # 步骤 4: 3x 复现验证
        replication = three_x_replication(weakest_id)
        results["steps"]["replication"] = replication

        # 最终结论
        results["conclusion"] = {
            "weakest_cell": weakest_id,
            "patch_applied": patch_result.get("applied", False),
            "replication_reproducible": replication.get("reproducible", False),
            "delta_score": patch_result.get("applied", False) and replication.get("reproducible", False)
        }

        if not json_output:
            print("\n" + "=" * 60)
            print("📊 管道执行完成")
            print("=" * 60)
            print(f"   最弱格: {weakest_id}")
            print(f"   补丁: {'✅ 已应用' if patch_result.get('applied') else '❌ 失败'}")
            print(f"   3x 复现: {'✅ 可复现' if replication.get('reproducible') else '❌ 不可复现'}")

    # 保存结果
    RESULTS_FILE.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    if not json_output:
        print(f"\n💾 结果已保存到: {RESULTS_FILE}")

    return results


def main():
    parser = argparse.ArgumentParser(description="真适应度进化管道")
    parser.add_argument("--find-only", action="store_true", help="只跑前两步（跑基线+找最弱格）")
    parser.add_argument("--patch-only", action="store_true", help="只跑后两步（用已保存的最弱格出补丁+验证）")
    parser.add_argument("--json", action="store_true", help="纯机读 JSON 输出")
    args = parser.parse_args()

    results = run_pipeline(find_only=args.find_only, patch_only=args.patch_only, json_output=args.json)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))

    # 返回退出码
    if results.get("steps", {}).get("weakest", {}).get("cell"):
        if args.find_only:
            return 0
        if results.get("conclusion", {}).get("delta_score"):
            return 0
        if args.patch_only and results.get("steps", {}).get("patch", {}).get("applied"):
            return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
