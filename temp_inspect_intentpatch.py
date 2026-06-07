"""临时：用 intentpatch 编制补丁"""
import sys
sys.path.insert(0, str(Path(__file__).parent))
from intentpatch import IntentPatch

# 读取 canary.py
with open("canary.py") as f:
    original = f.read()

# 编制补丁：针对定位到的真死因
# 如果 dead_branch 是 always-False-if 或 always-True-if，修复它
patch = IntentPatch.from_target("canary.py", original)

# 假设 astlocator 发现 _check_no_circular_deps 有死分支
# 构造 <10 行补丁
intent_patch = """
# intent: fix dead branch in _check_no_circular_deps
# replace the overly broad except with precise exception types
"""

# 这里用 intentpatch 解析并生成实际补丁代码
print("IntentPatch 准备就绪")
print(patch.intent)
