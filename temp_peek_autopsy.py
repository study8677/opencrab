"""临时读取 autopsy_do_canary_75_final.py 的实际代码片段"""
from pathlib import Path

# 读取 do_canary_75_final.py
path = Path("do_canary_75_final.py")
if path.exists():
    source = path.read_text()
    # 找 step3 和 step5 的实现
    print("=== do_canary_75_final.py 源码片段 ===")
    print(source[source.find("def step3"):source.find("def step3")+800] if "def step3" in source else "NO step3")
    print("\n=== step5 ===")
    print(source[source.find("def step5"):source.find("def step5")+800] if "def step5" in source else "NO step5")
else:
    print("do_canary_75_final.py 不存在")
