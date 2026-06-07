"""
诊断 run_fitness_baseline.py 依赖的四个模块：
arena / boundaryeval / regression / canary
探明其 __init__ 接口、run() 签名、quick 参数支持。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent

MODULES = {
    "arena": "arena.py",
    "boundaryeval": "boundaryeval.py",
    "regression": "regression.py",
    "canary": "canary.py",
}

results = {}

for name, filename in MODULES.items():
    filepath = REPO_ROOT / filename
    print(f"\n{'='*50}")
    print(f"模块: {name}  ({filename})")
    print(f"文件存在: {filepath.exists()}")

    if not filepath.exists:
        results[name] = "FILE_NOT_FOUND"
        print("  → 文件不存在，跳过")
        continue

    # 1. 尝试 import
    try:
        mod = __import__(name)
        print(f"  → import 成功: {mod}")
    except Exception as e:
        print(f"  → import 失败: {e}")
        results[name] = f"IMPORT_ERROR: {e}"
        continue

    # 2. 检查类
    class_map = {
        "arena": "Arena",
        "boundaryeval": "BoundaryEval",
        "regression": "RegressionSuite",
        "canary": "Canary",
    }
    cls_name = class_map[name]
    cls = getattr(mod, cls_name, None)
    if cls is None:
        print(f"  → 类 {cls_name} 未找到，可用: {[x for x in dir(mod) if not x.startswith('_')]}")
        results[name] = f"CLASS_NOT_FOUND: {cls_name}"
        continue
    print(f"  → 类 {cls_name} 存在: {cls}")

    # 3. 检查 __init__ 签名
    import inspect
    try:
        sig = inspect.signature(cls.__init__)
        params = list(sig.parameters.keys())
        print(f"  → __init__ 参数: {params}")
        has_quick = "quick" in params
        print(f"  → quick 参数: {'✅ 支持' if has_quick else '❌ 不支持'}")
    except Exception as e:
        print(f"  → 签名检查失败: {e}")
        has_quick = False

    # 4. 检查 run() 方法
    run_method = getattr(cls, "run", None)
    if run_method is None:
        print(f"  → run() 方法未找到")
        results[name] = "NO_RUN_METHOD"
        continue
    print(f"  → run() 存在: {run_method}")

    # 5. 尝试实例化 + run (quick=True)
    try:
        inst = cls(quick=True)
        print(f"  → 实例化(quick=True) 成功")
    except TypeError as te:
        # quick 参数不支持
        try:
            inst = cls()
            print(f"  → 实例化() 成功 (quick 参数不支持)")
        except Exception as e2:
            print(f"  → 实例化失败: {e2}")
            results[name] = f"INSTANTIATE_ERROR: {e2}"
            continue
    except Exception as e:
        print(f"  → 实例化(quick=True) 失败: {e}")
        results[name] = f"INSTANTIATE_ERROR: {e}"
        continue

    # 6. 调用 run()
    try:
        result = inst.run()
        print(f"  → run() 返回: {result}")
        print(f"  → 返回类型: {type(result)}")
        if isinstance(result, dict):
            print(f"  → keys: {list(result.keys())}")
            for k in ["passed", "failed", "total"]:
                print(f"     {k}: {result.get(k, 'N/A')}")
        results[name] = {"result": result, "quick_supported": has_quick}
    except NotImplementedError as e:
        print(f"  → run() 未实现: {e}")
        results[name] = "RUN_NOT_IMPLEMENTED"
    except Exception as e:
        print(f"  → run() 失败: {e}")
        results[name] = f"RUN_ERROR: {e}"

print("\n" + "=" * 50)
print("诊断汇总:")
for name, status in results.items():
    print(f"  {name}: {status}")
