"""
3 闸检查：canary.py 修复后必须过此三闸
"""
import ast
import json
import subprocess
from pathlib import Path

CANARY = Path(__file__).parent / "canary.py"
FIXED_CANARY = Path(__file__).parent / "canary.py"

class ThreeGates:
    def __init__(self):
        self.results = {}
    
    def gate1_syntax_and_import(self) -> bool:
        """第一闸：语法正确 + 可导入"""
        try:
            ast.parse(FIXED_CANARY.read_text())
            import importlib.util
            spec = importlib.util.spec_from_file_location("canary_test", FIXED_CANARY)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.results["gate1"] = "✅ 语法正确，模块可导入"
            return True
        except Exception as e:
            self.results["gate1"] = f"❌ {e}"
            return False
    
    def gate2_logic_fixed(self) -> bool:
        """第二闸：逻辑已修复（不再有 >= 0 的永恒 True）"""
        source = FIXED_CANARY.read_text()
        # 检查是否还存在永恒 True 的缺陷模式
        if ">= 0  # 总是返回 True" in source or ">= 0  # 至少一个文件才算有活动" not in source:
            # 如果旧的注释还在，或者新的正确逻辑不在
            if "return len(list(evidence_dir.iterdir())) >= 0" in source:
                self.results["gate2"] = "❌ 缺陷仍存在"
                return False
        
        # 确认修复后是 > 0
        if "> 0" in source and "_check_recent_activity" in source:
            self.results["gate2"] = "✅ 逻辑已修复：>= 0 改为 > 0"
            return True
        self.results["gate2"] = "❌ 修复逻辑不正确"
        return False
    
    def gate3_canary_run_ok(self) -> bool:
        """第三闸：canary.py 能正常运行"""
        try:
            result = subprocess.run(
                ["python", str(FIXED_CANARY)],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                self.results["gate3"] = f"✅ 运行成功: {result.stdout.strip()}"
                return True
            else:
                self.results["gate3"] = f"❌ 运行失败: {result.stderr}"
                return False
        except Exception as e:
            self.results["gate3"] = f"❌ 异常: {e}"
            return False
    
    def run_all(self) -> dict:
        g1 = self.gate1_syntax_and_import()
        g2 = self.gate2_logic_fixed()
        g3 = self.gate3_canary_run_ok()
        passed = sum([g1, g2, g3])
        self.results["summary"] = f"通过 {passed}/3 闸"
        return self.results

if __name__ == "__main__":
    gates = ThreeGates()
    results = gates.run_all()
    print("\n=== 3 闸检查结果 ===")
    for k, v in results.items():
        print(f"  {k}: {v}")
    
    assert results.get("summary", "").startswith("通过 3/3"), "3闸未全过！"
    print("\n🎉 3 闸全过！")
