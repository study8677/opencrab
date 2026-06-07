#!/usr/bin/env python3
"""快速摸清 canary 75% 的当前状态"""
import json, sys
sys.path.insert(0, '.')
from crab import read_state, PROJECTS_DIR

def peek():
    state = read_state()
    fitness = state.get('fitness', {})
    print("=== 当前 fitness 概况 ===")
    print(json.dumps(fitness, indent=2))
    
    # 看看最弱格子在哪
    grid = fitness.get('grid', {})
    if grid:
        weakest = min(grid.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 999)
        print(f"\n=== 最弱格子: {weakest[0]} = {weakest[1]} ===")
    
    # 看 projects 目录有哪些项目
    import os
    if os.path.exists(PROJECTS_DIR):
        projects = sorted(os.listdir(PROJECTS_DIR))
        print(f"\n=== PROJECTS_DIR ({PROJECTS_DIR}) 项目数: {len(projects)} ===")
        print(projects[:10])

if __name__ == '__main__':
    peek()
