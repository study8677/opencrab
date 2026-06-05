"""
astlocator 专用：定位 canary.py 的真缺陷
"""
import ast
from pathlib import Path

CANARY = Path(__file__).parent / "canary.py"

def find_real_defect():
    """找到 _check_recent_activity 中 return len(...) >= 0 的永恒 True bug"""
    source = CANARY.read_text()
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_check_recent_activity":
            # 找 return len(...) >= 0 节点
            for child in ast.walk(node):
                if isinstance(child, ast.Compare) and isinstance(child.left, ast.Call):
                    # 左边是 len() 调用，右边是 >= 0
                    if (isinstance(child.ops[0], ast.GtE) and
                        isinstance(child.comparators[0], ast.Constant) and
                        child.comparators[0].value == 0):
                        return {
                            "defect": "eternal_true",
                            "location": f"line {child.lineno}",
                            "detail": "return len(...) >= 0 always True",
                            "fix_hint": "should check len(...) > 0"
                        }
    return None

if __name__ == "__main__":
    defect = find_real_defect()
    print(f"定位到的真缺陷: {defect}")
    assert defect, "未找到永恒 True bug！"
    print("✅ 缺陷已锁定：_check_recent_activity 中 `len(...) >= 0` 永远为 True")
    print("   正确逻辑应该是 `len(...) > 0` 或 `len(...) >= 1`")
