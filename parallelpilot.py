"""
parallelpilot - 并行领航
同时推进三个互不依赖的低风险任务，验证并发推进能力
任务：
  1. 展示页刷新 (showcase_refresher)
  2. 能力图谱自检 (skillgraph)
  3. 冷启动演练 (coldstart_offline_rehearsal)
"""

import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed


def _task_showcase_refresh():
    """任务1：展示页刷新 - 回应外界信号"""
    import showcase_refresher
    return showcase_refresher.run()


def _task_skillgraph_check():
    """任务2：能力图谱自检"""
    import skillgraph
    return skillgraph.check()


def _task_coldstart_drill():
    """任务3：冷启动演练"""
    import coldstart_offline_rehearsal
    return coldstart_offline_rehearsal.run()


def run_parallel_pilot():
    """执行并行航次，同时推进三个任务"""
    results = {}
    errors = {}
    start = time.time()

    tasks = {
        "showcase_refresh": _task_showcase_refresh,
        "skillgraph_check": _task_skillgraph_check,
        "coldstart_drill": _task_coldstart_drill,
    }

    print("[parallelpilot] 🚀 启动并行航次：3个任务同时出发")
    print(f"  任务: {', '.join(tasks.keys())}")

    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_task = {}
        for name, task_fn in tasks.items():
            future = executor.submit(_run_task_safe, name, task_fn)
            future_to_task[future] = name

        for future in as_completed(future_to_task):
            task_name = future_to_task[future]
            try:
                result = future.result()
                if result["success"]:
                    results[task_name] = result
                    print(f"  ✅ {task_name} 完成 ({result['duration']:.1f}s)")
                else:
                    errors[task_name] = result
                    print(f"  ❌ {task_name} 失败: {result['error']}")
            except Exception as e:
                errors[task_name] = {"success": False, "error": str(e), "traceback": traceback.format_exc()}
                print(f"  ❌ {task_name} 异常: {e}")

    elapsed = time.time() - start
    success_count = len(results)
    total = len(tasks)

    report = {
        "success": success_count == total,
        "elapsed": elapsed,
        "success_count": success_count,
        "total": total,
        "results": results,
        "errors": errors,
    }

    print(f"[parallelpilot] 🛬 航次完成: {success_count}/{total} 成功 ({elapsed:.1f}s)")
    return report


def _run_task_safe(name, task_fn):
    """安全执行单个任务，捕获异常"""
    start = time.time()
    try:
        result = task_fn()
        return {
            "success": True,
            "duration": time.time() - start,
            "result": result
        }
    except Exception as e:
        return {
            "success": False,
            "duration": time.time() - start,
            "error": str(e),
            "traceback": traceback.format_exc()
        }


def main():
    """主入口：运行并行航次并输出结果"""
    report = run_parallel_pilot()
    if report["success"]:
        print("\n[parallelpilot] ✅ 并行航次验证通过 - 三个任务互不干扰并发完成")
    else:
        print(f"\n[parallelpilot] ⚠️  部分任务失败 ({report['success_count']}/{report['total']})")
        for name, error in report["errors"].items():
            print(f"  - {name}: {error['error']}")
    return 0 if report["success"] else 1


if __name__ == "__main__":
    exit(main())
