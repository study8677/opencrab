#!/usr/bin/env python3
"""跑 fitness baseline，获取真实分数"""
import sys, time, json
sys.path.insert(0, '.')
from crab import fitness_replication_protocol, read_state, write_state

def run_baseline():
    print("=== 开始跑 fitness baseline ===")
    state = read_state()
    current = state.get('fitness', {})
    print(f"跑前分数: {json.dumps(current, indent=2)}")
    
    start = time.time()
    result = fitness_replication_protocol()  # 这应该是跑 fitness 的核心函数
    elapsed = time.time() - start
    
    print(f"\n=== baseline 跑完，耗时 {elapsed:.1f}s ===")
    print(json.dumps(result, indent=2))
    
    # 更新 state
    state['fitness'] = result
    write_state(state)
    print("状态已写入 crab_state.json")
    
    return result

if __name__ == '__main__':
    run_baseline()
