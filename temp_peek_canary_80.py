import sys
sys.path.insert(0, '.')
from peek_fitness_json import read_fitness_json
import json

# 读取当前 fitness.json
fitness = read_fitness_json()
print("=== CURRENT FITNESS JSON ===")
print(json.dumps(fitness, indent=2))
