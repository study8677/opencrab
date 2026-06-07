#!/usr/bin/env python3
"""
快速扫描 boundaryeval 和 arena 的 fitness 基线状态
"""
import os, json
from pathlib import Path

def peek_fitness_ledger(target):
    """查看某 target 的 fitness ledger"""
    ledger = Path(f"projects/{target}/fitness.json")
    if ledger.exists():
        data = json.loads(ledger.read_text())
        return data
    return None

def scan_boundaries():
    """扫描所有 boundaryeval 相关文件的状态"""
    results = {}
    
    # 1. boundaryeval.py 主模块
    be_path = Path("boundaryeval.py")
    if be_path.exists():
        results['boundaryeval_main'] = {
            'size': be_path.stat().st_size,
            'modified': os.path.getmtime(str(be_path))
        }
    
    # 2. 各种 regression 文件
    reg_files = [
        'boundaryeval_regression.py',
        'boundaryeval_aegis_absorption_regression.py', 
        'boundaryeval_malicious_intent_regression.py',
        'boundaryeval_redteam_regression.py',
    ]
    for f in reg_files:
        p = Path(f)
        if p.exists():
            results[f.replace('.py','')] = {
                'size': p.stat().st_size,
                'modified': os.path.getmtime(str(p))
            }
    
    # 3. 扫描 projects/ 目录
    projects_dir = Path("projects")
    if projects_dir.exists():
        for proj in projects_dir.iterdir():
            if proj.is_dir():
                fitness_file = proj / "fitness.json"
                if fitness_file.exists():
                    try:
                        data = json.loads(fitness_file.read_text())
                        results[f'projects/{proj.name}'] = {
                            'has_fitness': True,
                            'scores': data.get('scores', {}),
                            'brain_only': data.get('brain_only', None)
                        }
                    except:
                        results[f'projects/{proj.name}'] = {'has_fitness': True, 'parse_error': True}
    
    return results

def main():
    print("=== BoundaryEval & Arena Fitness Scan ===\n")
    
    # 检查 projects/arena 和 projects/boundaryeval
    for target in ['arena', 'boundaryeval']:
        print(f"--- {target} ---")
        fitness = peek_fitness_ledger(target)
        if fitness:
            print(f"  fitness.json 存在")
            print(f"  scores: {json.dumps(fitness.get('scores',{}), indent=4)}")
            print(f"  brain_only: {fitness.get('brain_only')}")
            print(f"  best_score: {fitness.get('best_score')}")
        else:
            print(f"  尚无 fitness.json (需要先建基线)")
        print()
    
    # 扫描其他文件
    print("--- 相关文件状态 ---")
    file_status = scan_boundaries()
    for name, info in file_status.items():
        if 'scores' in info:
            print(f"{name}: scores={info['scores']}")
        else:
            print(f"{name}: size={info.get('size',0)}, modified={info.get('modified',0):.0f}")
    print()

if __name__ == '__main__':
    main()
