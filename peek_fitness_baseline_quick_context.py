#!/usr/bin/env python3
"""临时：查看 run_fitness_baseline_quick 所需的上下文文件"""
import os, json

print("=== 1. 查看 fitness.json 是否存在 ===")
fitness_json_path = 'fitness.json'
if os.path.exists(fitness_json_path):
    with open(fitness_json_path) as f:
        data = json.load(f)
    print(json.dumps(data, indent=2))
else:
    print("fitness.json 不存在")

print("\n=== 2. 查看 crab_state.json 的 fitness 部分 ===")
state_path = 'crab_state.json'
if os.path.exists(state_path):
    with open(state_path) as f:
        state = json.load(f)
    fitness = state.get('fitness', {})
    print(json.dumps(fitness, indent=2))
else:
    print("crab_state.json 不存在")

print("\n=== 3. 查看 crab.py 中 fitness_replication_protocol 的签名 ===")
with open('crab.py') as f:
    content = f.read()
# 找 fitness 相关函数
import re
for match in re.finditer(r'def fitness_replication_protocol\([^)]*\):', content):
    start = match.start()
    print(content[start:start+300])
    print("...")
    break

print("\n=== 4. 查看 patchfitroom.py 结构 ===")
if os.path.exists('patchfitroom.py'):
    with open('patchfitroom.py') as f:
        content = f.read()
    print(content[:2000])
else:
    print("patchfitroom.py 不存在")
