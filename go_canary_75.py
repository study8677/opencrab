#!/usr/bin/env python3
"""
go_canary_75.py - 一键对最弱格 canary 75% 下刀

直接执行:
1. reproduce_canary_3x 找挂的 case
2. readpack 圈最小修面
3. brain-only 出补丁
4. 过三闸并入
5. 让 canary 真分涨

不说"跑基线"，直接动手。
"""

import subprocess
import sys

def run(cmd, desc=""):
    """运行命令并打印输出"""
    if desc:
        print(f"\n{'='*60}")
        print(f"{desc}")
        print(f"{'='*60}")
    
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(f"STDERR: {result.stderr[:500]}")
    return result.returncode

def main():
    print("""
╔══════════════════════════════════════════════════════════════╗
║         CANARY 75% EVOLUTION - 对最弱格下刀                    ║
║                                                              ║
║  1. reproduce_canary_3x 找挂的 case                          ║
║  2. readpack 圈最小修面                                        ║
║  3. brain-only 出补丁                                         ║
║  4. 过三闸并入                                                 ║
║  5. 让 canary 真分涨                                           ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Step 1: 找挂的 case
    rc = run("python reproduce_canary_3x.py 2>&1 | head -50", "Step 1: 找挂的 case")
    
    # Step 2: readpack 圈最小修面
    print("\n" + "="*60)
    print("Step 2: readpack 圈最小修面")
    print("="*60)
    
    from pathlib import Path
    for f in ["crab.py", "hands.py", "brain.py"]:
        if Path(f).exists():
            run(f"python readpack.py --file {f} 2>&1", f"readpack {f}")
    
    # Step 3: brain-only 出补丁
    print("\n" + "="*60)
    print("Step 3: brain-only 出补丁")
    print("="*60)
    run("python brainonly_canary_patch.py --case canary_75 2>&1", "brainonly patch")
    
    # Step 4: 过三闸
    print("\n" + "="*60)
    print("Step 4: 过三闸")
    print("="*60)
    run("python check_three_gates_canary.py 2>&1", "three gates")
    
    # Step 5: 并入
    print("\n" + "="*60)
    print("Step 5: 并入")
    print("="*60)
    run("git add -A && git commit -m 'canary 75% evolution patch' 2>&1 || echo 'No changes to commit'", "git commit")
    
    # Step 6: 验证
    print("\n" + "="*60)
    print("Step 6: 验证 canary 真分涨")
    print("="*60)
    run("python -c \"from check_fitness_json import check_fitness; print(f'Fitness: {check_fitness()}')\"", "fitness check")
    
    print("\n" + "="*60)
    print("DONE - canary 真分涨了吗？")
    print("="*60)

if __name__ == "__main__":
    main()
