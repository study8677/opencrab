"""
heartbeat_tasks.py – 心跳周期任务定义

定义需要定期执行的自维护任务及其执行间隔。
由 heartbeat.py 的 auto_integrate_heartbeat() 在模块加载时自动导入。
"""


def add_heartbeat_tasks(tasks):
    """添加需要定期执行的自维护任务到心跳任务列表（与 heartbeat.TASKS 格式对齐）"""
    tasks.append({
        'module': 'docsync',
        'func_name': 'run',
        'desc': '文档真伪自动核对',
        'interval': 7200,
    })
    tasks.append({
        'module': 'cli_probe',
        'func_name': 'run',
        'desc': 'CLI坏入口预警',
        'interval': 1800,
    })
    tasks.append({
        'module': 'evidence_refresher',
        'func_name': 'run',
        'desc': '证据批量续期',
        'interval': 3600,
    })
    tasks.append({
        'module': 'sync_docs_numbers',
        'func_name': 'update_html',
        'desc': '橱窗数字自动同步',
        'interval': 3600,
    })
    tasks.append({
        'module': 'showcase_refresher',
        'func_name': 'update_showcase',
        'desc': '橱窗模块计数刷新',
        'interval': 3600,
    })
