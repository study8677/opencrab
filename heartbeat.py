"""
heartbeat.py – 日常任务自动触发器

在每次进化拍开始时自动运行证据刷新、展示站刷新、模块健康检查等任务。
任务列表可根据实际情况扩展或调整。
"""

import importlib
import logging
from typing import List, Dict, Callable, Any

# 日志配置
logger = logging.getLogger(__name__)

# 任务注册表：每个任务描述需要导入的模块和函数
TASKS: List[Dict[str, Any]] = [
    {
        "module": "evidence_freshness",
        "func_name": "run",  # 假设 evidence_freshness.run() 执行刷新
        "desc": "刷新证据新鲜度"
    },
    {
        "module": "showcase_refresher",
        "func_name": "run",  # 假设 showcase_refresher.run() 执行刷新
        "desc": "刷新展示站数字"
    },
    {
        "module": "organ_autodiag",
        "func_name": "run",  # 假设 organ_autodiag.run() 执行健康检查
        "desc": "执行模块健康检查"
    },
]

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

def register_task(module: str, func_name: str, desc: str) -> None:
    """
    动态注册一个新任务到心跳中。
    """
    TASKS.append({
        "module": module,
        "func_name": func_name,
        "desc": desc,
    })
    logger.debug(f"已注册新任务: {module}.{func_name} – {desc}")

# 命令行接口：直接运行 python heartbeat.py 可手动触发
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run_heartbeat()
