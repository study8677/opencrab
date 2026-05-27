# heartbeat_tasks.py
from . import evidence_freshness, docsync, cli_probe

def add_heartbeat_tasks(tasks):
    """添加需要定期执行的自维护任务"""
    tasks.append({
        'name': 'evidence_freshness',
        'func': evidence_freshness.run,
        'interval': 3600,  # 每小时检查一次证据新鲜度
        'description': '自动重验过期证据'
    })
    tasks.append({
        'name': 'docsync',
        'func': docsync.run,
        'interval': 7200,  # 每两小时核对一次文档真伪
        'description': '文档真伪自动核对'
    })
    tasks.append({
        'name': 'cli_probe',
        'func': cli_probe.run,
        'interval': 1800,  # 每半小时检查一次CLI入口
        'description': 'CLI坏入口预警'
    })
