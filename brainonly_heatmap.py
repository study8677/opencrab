"""统计近30次brain-only改码触达函数，生成热图并回灌tiergate盲区"""

import collections
from datetime import datetime, timedelta

# 存储最近30次brain-only操作的函数触达记录
_brainonly_records = collections.deque(maxlen=30)

def record_brainonly_touch(function_names: list[str], timestamp: datetime = None):
    """记录一次brain-only操作触达的函数列表"""
    if timestamp is None:
        timestamp = datetime.now()
    _brainonly_records.append({
        'timestamp': timestamp,
        'functions': set(function_names)
    })

def get_heatmap() -> dict[str, int]:
    """返回函数触达频率热图（函数名 -> 触达次数）"""
    heatmap = {}
    for record in _brainonly_records:
        for func in record['functions']:
            heatmap[func] = heatmap.get(func, 0) + 1
    return heatmap

def get_blind_spots(all_functions: list[str]) -> list[str]:
    """返回未触达的盲区函数列表"""
    heatmap = get_heatmap()
    return [f for f in all_functions if f not in heatmap]

def feed_blindspots_to_tiergate():
    """将盲区函数回灌到tiergate"""
    try:
        from tiergate import report_blindspots
        # 获取当前所有已知函数（假设从crab模块获取）
        import crab
        all_functions = []
        for attr in dir(crab):
            if callable(getattr(crab, attr)) and not attr.startswith('_'):
                all_functions.append(attr)
        
        blindspots = get_blind_spots(all_functions)
        if blindspots:
            report_blindspots(blindspots)
    except Exception as e:
        print(f"Failed to feed blindspots to tiergate: {e}")

def get_recent_touches(hours: int = 24) -> dict[str, int]:
    """返回最近指定小时内各函数的触达次数"""
    cutoff = datetime.now() - timedelta(hours=hours)
    heatmap = {}
    for record in _brainonly_records:
        if record['timestamp'] > cutoff:
            for func in record['functions']:
                heatmap[func] = heatmap.get(func, 0) + 1
    return heatmap
