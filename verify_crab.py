#!/usr/bin/env python3
"""验证 crab 可导入"""

import sys

try:
    import crab
    print(f"✓ crab 导入成功")
    print(f"  路径: {crab.__file__}")
    print(f"  版本: {crab.__version__}")
except Exception as e:
    print(f"✗ crab 导入失败: {e}")
    sys.exit(1)

# 检查新添加的函数
if hasattr(crab, 'get_fitness'):
    print(f"✓ crab.get_fitness() = {crab.get_fitness()}")
else:
    print("○ crab.get_fitness() 不存在 (这是正常的)")

print("\n✓ 所有验证通过")
