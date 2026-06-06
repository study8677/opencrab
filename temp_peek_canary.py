import readpack
import astlocator
import intentpatch
import patchfitroom

# 看看各模块的入口函数
print("=== readpack ===")
print([x for x in dir(readpack) if not x.startswith('_')])

print("=== astlocator ===")
print([x for x in dir(astlocator) if not x.startswith('_')])

print("=== intentpatch ===")
print([x for x in dir(intentpatch) if not x.startswith('_')])

print("=== patchfitroom ===")
print([x for x in dir(patchfitroom) if not x.startswith('_')])
