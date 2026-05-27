"""测试brainonly_heatmap模块"""

import pytest
from datetime import datetime, timedelta
from brainonly_heatmap import (
    record_brainonly_touch,
    get_heatmap,
    get_blind_spots,
    get_recent_touches,
    _brainonly_records
)

def setup_function():
    """每个测试前清空记录"""
    _brainonly_records.clear()

def test_record_brainonly_touch():
    record_brainonly_touch(['func_a', 'func_b'])
    assert len(_brainonly_records) == 1
    assert 'func_a' in _brainonly_records[0]['functions']
    assert 'func_b' in _brainonly_records[0]['functions']

def test_heatmap():
    record_brainonly_touch(['func_a', 'func_b'])
    record_brainonly_touch(['func_a', 'func_c'])
    
    heatmap = get_heatmap()
    assert heatmap['func_a'] == 2
    assert heatmap['func_b'] == 1
    assert heatmap['func_c'] == 1

def test_blind_spots():
    record_brainonly_touch(['func_a', 'func_b'])
    all_functions = ['func_a', 'func_b', 'func_c', 'func_d']
    
    blindspots = get_blind_spots(all_functions)
    assert 'func_c' in blindspots
    assert 'func_d' in blindspots
    assert 'func_a' not in blindspots
    assert 'func_b' not in blindspots

def test_max_records():
    """测试记录上限为30"""
    for i in range(35):
        record_brainonly_touch([f'func_{i}'])
    
    assert len(_brainonly_records) == 30
    # 最早的5条记录应该被丢弃
    assert 'func_0' not in _brainonly_records[0]['functions']
    assert 'func_4' not in _brainonly_records[0]['functions']
    assert 'func_5' in _brainonly_records[0]['functions']

def test_recent_touches():
    # 2小时前的记录
    old_time = datetime.now() - timedelta(hours=3)
    record_brainonly_touch(['old_func'], timestamp=old_time)
    
    # 现在的记录
    record_brainonly_touch(['new_func'])
    
    recent = get_recent_touches(hours=2)
    assert 'old_func' not in recent
    assert 'new_func' in recent
