"""
heartbeat.py – 日常任务自动触发器

在每次进化拍开始时自动运行证据刷新、展示站刷新、模块健康检查等任务。
任务列表可根据实际情况扩展或调整。
"""

import importlib
import json
import logging
import os
import time
from typing import List, Dict, Callable, Any

# 日志配置
logger = logging.getLogger(__name__)

# 任务注册表：每个任务描述需要导入的模块和函数
TASKS: List[Dict[str, Any]] = [
    {
        "module": "evidence_freshness",
        "func_name": "run",
        "desc": "刷新证据新鲜度",
        "interval": 3600,
    },
    {
        "module": "showcase_refresher",
        "func_name": "run",
        "desc": "刷新展示站数字",
        "interval": 7200,
    },
    {
        "module": "organ_autodiag",
        "func_name": "run",
        "desc": "执行模块健康检查",
        "interval": 3600,
    },
    {
        "module": "checkup",
        "func_name": "run",
        "desc": "执行系统检查",
        "interval": 1800,
    },
    {
        "module": "health",
        "func_name": "run",
        "desc": "执行健康监控",
        "interval": 900,
    },
    # ---- 以下为本次审计补上的缺口 ----
    {
        "module": "driftwatch",
        "func_name": "run",
        "desc": "监控领地漂移",
        "interval": 3600,
    },
    {
        "module": "trustscore",
        "func_name": "run",
        "desc": "更新信任评分",
        "interval": 3600,
    },
    {
        "module": "budget",
        "func_name": "run",
        "desc": "检查资源预算",
        "interval": 1800,
    },
    {
        "module": "consistency",
        "func_name": "run",
        "desc": "执行一致性检查",
        "interval": 3600,
    },
    {
        "module": "sentinel",
        "func_name": "run",
        "desc": "哨兵巡检",
        "interval": 1800,
    },
    {
        "module": "usageheat",
        "func_name": "run",
        "desc": "监控使用热度",
        "interval": 3600,
    },
    {
        "module": "secretscan",
        "func_name": "run",
        "desc": "扫描敏感信息泄露",
        "interval": 86400,
    },
    {
        "module": "licenseguard",
        "func_name": "run",
        "desc": "许可证合规检查",
        "interval": 86400,
    },
    {
        "module": "evidence_repair_queue",
        "func_name": "run",
        "desc": "处理证据修复队列",
        "interval": 1800,
    },
]

# ---- 状态持久化：记录每个任务上次运行时间 ----
_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".heartbeat_state.json")


def _load_state() -> dict:
    try:
        with open(_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(state: dict) -> None:
    with open(_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def run_heartbeat(tasks: List[Dict[str, Any]] = None) -> None:
    """
    运行所有注册的心跳任务。
    
    参数:
        tasks: 可选，任务列表，默认使用模块级 TASKS
    """
    if tasks is None:
        tasks = TASKS
    
    logger.info("💓 心跳任务开始执行")
    success_count = 0
    for task in tasks:
        mod_name = task["module"]
        func_name = task["func_name"]
        desc = task["desc"]
        try:
            mod = importlib.import_module(mod_name)
            func: Callable = getattr(mod, func_name)
            logger.info(f"  ▸ 执行 {desc} ({mod_name}.{func_name})")
            func()
            success_count += 1
        except ImportError:
            logger.warning(f"  ⚠ 模块 {mod_name} 未找到，跳过 {desc}")
        except AttributeError:
            logger.warning(f"  ⚠ 函数 {mod_name}.{func_name} 不存在，跳过 {desc}")
        except Exception as e:
            logger.error(f"  ✗ 执行 {desc} 时出错: {e}")
    
    logger.info(f"💓 心跳任务完成 ({success_count}/{len(tasks)} 项成功)")

def tick(tasks: List[Dict[str, Any]] = None) -> None:
    """
    间隔感知的心跳：只运行到期的任务，执行后持久化时间戳。
    每个任务可通过 "interval" 字段指定最小间隔（秒），默认 3600。

    适合被 cron 或 cadence 周期调用：python heartbeat.py --tick
    """
    if tasks is None:
        tasks = TASKS

    state = _load_state()
    now = time.time()
    logger.info("💓 心跳 tick 开始检查")
    ran = 0
    skipped = 0
    for task in tasks:
        key = f"{task['module']}.{task['func_name']}"
        interval = task.get("interval", 3600)
        last = state.get(key, 0)
        if now - last < interval:
            skipped += 1
            continue
        mod_name = task["module"]
        func_name = task["func_name"]
        desc = task["desc"]
        try:
            mod = importlib.import_module(mod_name)
            func: Callable = getattr(mod, func_name)
            logger.info(f"  ▸ [tick] 执行 {desc} ({mod_name}.{func_name})")
            func()
            state[key] = now
            ran += 1
        except ImportError:
            logger.warning(f"  ⚠ 模块 {mod_name} 未找到，跳过 {desc}")
        except AttributeError:
            logger.warning(f"  ⚠ 函数 {mod_name}.{func_name} 不存在，跳过 {desc}")
        except Exception as e:
            logger.error(f"  ✗ 执行 {desc} 时出错: {e}")

    _save_state(state)
    logger.info(f"💓 心跳 tick 完成：执行 {ran} 项，跳过 {skipped} 项（未到期）")


def register_task(module: str, func_name: str, desc: str, interval: int = 3600) -> None:
    """
    动态注册一个新任务到心跳中。
    """
    TASKS.append({
        "module": module,
        "func_name": func_name,
        "desc": desc,
        "interval": interval,
    })
    logger.debug(f"已注册新任务: {module}.{func_name} – {desc} (间隔 {interval}s)")

def auto_integrate_heartbeat() -> None:
    """
    尝试自动集成心跳任务到进化流程中。
    1. 导入 heartbeat_tasks 模块，将其任务注册到 TASKS
    2. 尝试导入 cadence 模块并注册心跳 tick，实现自动触发
    """
    # 加载 heartbeat_tasks 中定义的周期任务
    try:
        import heartbeat_tasks as _ht
        if hasattr(_ht, 'add_heartbeat_tasks'):
            before = len(TASKS)
            _ht.add_heartbeat_tasks(TASKS)
            logger.info(f"从 heartbeat_tasks 加载了 {len(TASKS) - before} 项任务，当前共 {len(TASKS)} 项")
    except ImportError:
        logger.debug("heartbeat_tasks 模块未找到")

    try:
        import cadence
        if hasattr(cadence, 'register_hook'):
            cadence.register_hook('evolution_start', tick)
            logger.info("心跳 tick 已自动注册到 cadence 的进化开始钩子")
        else:
            logger.debug("cadence 模块没有 register_hook 函数，无法自动注册")
    except ImportError:
        logger.debug("cadence 模块未找到，心跳任务未自动集成")

# 在模块导入时尝试自动集成
auto_integrate_heartbeat()

def audit_heartbeat_coverage() -> None:
    """
    审计心跳覆盖情况：
    1. 扫描领地内所有 .py 模块，找出有 run() 但未被心跳注册的「漏网之鱼」
    2. 检查心跳注册的模块是否真的存在
    """
    import os
    import inspect

    base_dir = os.path.dirname(os.path.abspath(__file__))
    registered = {t["module"] for t in TASKS}

    # 扫描领地内所有模块
    unregistered_with_run = []
    for fname in os.listdir(base_dir):
        if not fname.endswith(".py") or fname.startswith("_") or fname == "heartbeat.py":
            continue
        mod_name = fname[:-3]
        if mod_name in registered:
            continue
        try:
            spec = importlib.util.spec_from_file_location(mod_name, os.path.join(base_dir, fname))
            if spec and spec.loader:
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)
                if callable(getattr(mod, "run", None)):
                    unregistered_with_run.append(mod_name)
        except Exception:
            pass

    # 检查注册的模块是否存在文件
    missing_files = []
    for t in TASKS:
        fpath = os.path.join(base_dir, t["module"] + ".py")
        if not os.path.exists(fpath):
            missing_files.append(t["module"])

    print("=" * 50)
    print("💓 心跳覆盖审计报告")
    print("=" * 50)
    print(f"\n📋 已注册任务: {len(TASKS)} 项")
    for t in TASKS:
        print(f"   ✓ {t['module']}: {t['desc']}")

    if unregistered_with_run:
        print(f"\n⚠️  有 run() 但未被心跳覆盖的模块 ({len(unregistered_with_run)} 个):")
        for m in unregistered_with_run:
            print(f"   ✗ {m}")
    else:
        print("\n✅ 所有有 run() 的模块都已被心跳覆盖")

    if missing_files:
        print(f"\n❌ 心跳注册了但文件不存在的模块 ({len(missing_files)} 个):")
        for m in missing_files:
            print(f"   ✗ {m}")
    else:
        print("\n✅ 所有注册模块的文件都存在")
    print("=" * 50)


# 命令行接口：直接运行 python heartbeat.py 可手动触发
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    if "--audit" in sys.argv:
        audit_heartbeat_coverage()
    elif "--tick" in sys.argv:
        tick()
    elif "--status" in sys.argv:
        state = _load_state()
        if not state:
            print("💓 尚无心跳记录")
        else:
            print(f"💓 心跳状态 ({len(state)} 条记录):")
            for key, ts in sorted(state.items(), key=lambda x: -x[1]):
                elapsed = time.time() - ts
                print(f"  {key}: 上次 {elapsed:.0f} 秒前")
    else:
        run_heartbeat()
