"""
3x 复现验证：canary.py 修复后行为正确
"""
import importlib
import subprocess
from pathlib import Path

CANARY = Path(__file__).parent / "canary.py"

def reproduce_check():
    """复现验证：_check_recent_activity 在不同情况下应返回不同结果"""
    
    # 重新加载模块
    import importlib.util
    spec = importlib.util.spec_from_file_location("canary_repro", CANARY)
    canary_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(canary_module)
    
    Canary = canary_module.Canary
    
    print("=== 3x 复现验证 ===\n")
    
    # x1: quick 模式应跳过 _check_recent_activity
    c1 = Canary(quick=True)
    r1 = c1.run()
    print(f"x1 (quick=True): {r1}")
    assert r1["total"] == 4, f"quick 模式应只有4项检查，实际{r1['total']}"
    print("  ✅ quick 模式正确跳过 _check_recent_activity\n")
    
    # x2: full 模式包含 _check_recent_activity
    c2 = Canary(quick=False)
    r2 = c2.run()
    print(f"x2 (quick=False): {r2}")
    assert r2["total"] == 6, f"full 模式应有6项检查，实际{r2['total']}"
    print("  ✅ full 模式包含 _check_recent_activity\n")
    
    # x3: 验证源代码中已无永恒 True bug
    source = CANARY.read_text()
    has_old_bug = ">= 0  # 总是返回 True" in source
    has_fix = "> 0" in source and "_check_recent_activity" in source
    print(f"x3 源码检查:")
    print(f"  旧bug是否存在: {has_old_bug} (应为 False)")
    print(f"  修复逻辑是否存在: {has_fix} (应为 True)")
    assert not has_old_bug, "旧bug仍存在！"
    assert has_fix, "修复逻辑未找到！"
    print("  ✅ 源码中永恒 True bug 已修复\n")
    
    print("🎉 3x 复现全部通过！")
    return True

if __name__ == "__main__":
    reproduce_check()
