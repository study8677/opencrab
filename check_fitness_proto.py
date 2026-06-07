#!/usr/bin/env python3
"""检查 fitness_replication_protocol 返回什么"""
import sys
sys.path.insert(0, '.')
from crab import fitness_replication_protocol
import inspect

# 看看函数签名和文档
print("=== fitness_replication_protocol 源码 ===")
print(inspect.getsource(fitness_replication_protocol))
