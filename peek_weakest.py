#!/usr/bin/env python3
"""
peek_weakest.py - 快速查看最弱的 case
"""

import json
import subprocess
from pathlib import Path

def main():
    # 尝试多种方式找到最弱的 case
    
    # 方式1: 检查 fitness ledger
    ledger_path = Path("fitness_ledger.json")
    if ledger_path.exists():
        print("从 fitness_ledger.json 读取:")
        with open(ledger_path) as f:
            data = json.load(f)
        
        # 找最弱的
        if isinstance(data, dict) and 'cells' in data:
            cells = data['cells']
            sorted_cells = sorted(cells.items(), key=lambda x: x[1].get('score', 100) if isinstance(x[1], dict) else 100)
            
            print("\n最弱的 5 个 cell:")
            for cell_id, info in sorted_cells[:5]:
                score = info.get('score', 'N/A') if isinstance(info, dict) else 'N/A'
                print(f"  {cell_id}: {score}")
                
                # 检查是否 canary 75%
                if 'canary' in cell_id.lower() or '75' in str(score):
                    print(f"    -> 这是 canary 75%!")
    
    # 方式2: 直接运行测试看哪些失败
    print("\n" + "="*60)
    print("运行测试检查失败:")
    print("="*60)
    
    result = subprocess.run(
        ["python", "-m", "pytest", "tests/", "-v", "--tb=line", "-x"],
        capture_output=True,
        text=True,
    )
    
    print(result.stdout[-2000:] if len(result.stdout) > 2000 else result.stdout)
    
    # 找 FAILED 行
    for line in result.stdout.split('\n'):
        if 'FAILED' in line:
            print(f"FAILED: {line}")
    
    # 方式3: 尝试读取 check_three_gates_canary 的输出
    print("\n" + "="*60)
    print("检查三闸 canary:")
    print("="*60)
    
    result = subprocess.run(
        ["python", "check_three_gates_canary.py"],
        capture_output=True,
        text=True,
    )
    
    print(result.stdout[-1500:] if len(result.stdout) > 1500 else result.stdout)

if __name__ == "__main__":
    main()
