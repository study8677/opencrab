"""
brain-only 产出 canary.py 补丁
不调用任何外部工具，只靠对源码和缺陷的理解生成 patch
"""
from pathlib import Path

CANARY = Path(__file__).parent / "canary.py"
PATCH = Path(__file__).parent / "canary_fix.patch"

def brainonly_generate_patch():
    """
    脑内推理生成补丁：
    缺陷：_check_recent_activity 中 `return len(list(evidence_dir.iterdir())) >= 0`
    问题：长度永远 >= 0，所以永远返回 True
    修复：改为 `> 0`（至少有一个文件才算有活动）
    """
    # 原始有缺陷的代码片段
    broken = "return len(list(evidence_dir.iterdir())) >= 0  # 总是返回 True"
    # 修复后的代码片段
    fixed = "return len(list(evidence_dir.iterdir())) > 0   # 至少一个文件才算有活动"

    return broken, fixed

def apply_patch():
    """应用补丁到 canary.py"""
    broken, fixed = brainonly_generate_patch()
    source = CANARY.read_text()
    
    assert broken in source, "缺陷代码未找到，无法应用补丁"
    new_source = source.replace(broken, fixed, 1)
    CANARY.write_text(new_source)
    
    # 生成 patch 文件
    import difflib
    diff = difflib.unified_diff(
        source.splitlines(keepends=True),
        new_source.splitlines(keepends=True),
        fromfile='canary.py',
        tofile='canary.py (fixed)'
    )
    PATCH.write_text(''.join(diff))
    return True

if __name__ == "__main__":
    print("🧠 Brain-only 分析缺陷...")
    broken, fixed = brainonly_generate_patch()
    print(f"   缺陷: {broken}")
    print(f"   修复: {fixed}")
    print("\n🔧 应用补丁...")
    apply_patch()
    print(f"✅ 补丁已应用，diff 保存到 {PATCH}")
