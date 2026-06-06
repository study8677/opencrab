#!/usr/bin/env python3
"""验证成功后提交修复"""
import subprocess
import sys
import json
from pathlib import Path

def main():
    print("=== 提交 brain-only 修复 ===")
    
    # 1. 检查语法
    print("\n1. 检查语法...")
    result = subprocess.run(
        [sys.executable, "-m", "py_compile", 
         "apprentice_extractor.py", "astlocator.py", "patchfitroom.py"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"语法错误: {result.stderr}")
        sys.exit(1)
    print("✓ 语法检查通过")
    
    # 2. 更新 fitness.json
    print("\n2. 更新 fitness.json...")
    fitness_file = Path("fitness.json")
    if fitness_file.exists():
        with open(fitness_file) as f:
            fitness = json.load(f)
        
        # 添加本次修复记录
        if 'fixes' not in fitness:
            fitness['fixes'] = []
        fitness['fixes'].append({
            'type': 'brainonly_context_depth',
            'files': ['apprentice_extractor.py', 'astlocator.py', 'patchfitroom.py'],
            'description': 'Increased context depth from 2 to dynamic (max 3), added fuzzy matching, and implemented three validation gates in patchfitroom'
        })
        
        with open(fitness_file, 'w') as f:
            json.dump(fitness, f, indent=2)
        print("✓ fitness.json 已更新")
    
    # 3. Git 提交
    print("\n3. Git 提交...")
    result = subprocess.run(
        ["git", "add", "apprentice_extractor.py", "astlocator.py", "patchfitroom.py", "fitness.json"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"git add 失败: {result.stderr}")
    
    result = subprocess.run(
        ["git", "commit", "-m", "brainonly: improve context depth + fuzzy matching + validation gates"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"git commit 失败: {result.stderr}")
        sys.exit(1)
    print(f"✓ Git 提交成功: {result.stdout}")
    
    print("\n=== 修复完成 ===")

if __name__ == "__main__":
    main()
