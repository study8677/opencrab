import crab
import intent
import read_state

# 看看 crab.py 入口和主循环
import inspect
source = inspect.getsource(crab)
print("=== crab.py 关键部分 ===")
# 找主循环或 run 相关函数
for line in source.split('\n'):
    if 'def ' in line and ('run' in line.lower() or 'start' in line.lower() or 'main' in line.lower() or 'wake' in line.lower() or 'form_intent' in line.lower()):
        print(line)

print("\n=== intent.py 中的 form_intent ===")
src = inspect.getsource(intent)
for line in src.split('\n'):
    if 'form_intent' in line or '项目账' in line or 'state' in line:
        print(line)
        break  # 只看第一个

print("\n=== read_state.py ===")
src = inspect.getsource(read_state)
for i, line in enumerate(src.split('\n')[:50]):
    print(line)
