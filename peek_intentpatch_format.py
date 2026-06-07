# 偷看 intentpatch 格式
import intentpatch
import inspect
src = inspect.getsource(intentpatch)
print(src[:3000])
