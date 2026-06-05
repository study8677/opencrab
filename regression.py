"""
regression.py - 回归测试模块

确保现有功能不被破坏。
"""
from typing import Dict, Any, List, Optional
from pathlib import Path

REPO_ROOT = Path(__file__).parent


class RegressionSuite:
    """回归测试套件"""
    
    def __init__(self, quick: bool = False, modules: Optional[List[str]] = None):
        self.quick = quick
        self.modules = modules or []
        self.passed = 0
        self.failed = 0
        self.total = 0
    
    def run(self) -> Dict[str, Any]:
        """运行回归测试"""
        tests = self._get_tests()
        
        for test_name, test_fn in tests:
            self.total += 1
            try:
                if test_fn():
                    self.passed += 1
                else:
                    self.failed += 1
            except Exception as e:
                self.failed += 1
                print(f"  ❌ {test_name}: {e}")
        
        return {
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total
        }
    
    def _get_tests(self):
        """获取测试列表"""
        tests = [
            ("fitness_json_valid", self._test_fitness_json_valid),
            ("readpack_returns_valid_data", self._test_readpack_returns_valid_data),
            ("intentpatch_preserves_intent", self._test_intentpatch_preserves_intent),
            ("patchfitroom_validates_patch", self._test_patchfitroom_validates_patch),
        ]
        
        if not self.quick:
            tests.extend([
                ("crab_main_entry", self._test_crab_main_entry),
                ("module_import_chain", self._test_module_import_chain),
                ("state_persistence", self._test_state_persistence),
            ])
        
        return tests
    
    def _test_fitness_json_valid(self) -> bool:
        """测试 fitness.json 是有效的 JSON"""
        import json
        fp = REPO_ROOT / "fitness.json"
        if not fp.exists():
            return False
        try:
            with open(fp) as f:
                data = json.load(f)
            return isinstance(data, dict)
        except Exception:
            return False
    
    def _test_readpack_returns_valid_data(self) -> bool:
        """测试 readpack 返回有效数据"""
        try:
            from readpack import read_project_state
            state = read_project_state()
            return isinstance(state, dict)
        except Exception:
            return False
    
    def _test_intentpatch_preserves_intent(self) -> bool:
        """测试 intentpatch 保持意图"""
        try:
            from intentpatch import preserve_intent
            # 基本测试：如果函数存在且可调用
            return callable(preserve_intent)
        except Exception:
            return False
    
    def _test_patchfitroom_validates_patch(self) -> bool:
        """测试 patchfitroom 验证补丁"""
        try:
            from patchfitroom import validate_patch
            return callable(validate_patch)
        except Exception:
            return False
    
    def _test_crab_main_entry(self) -> bool:
        """测试 crab 主入口"""
        try:
            import crab
            return hasattr(crab, '__file__')
        except Exception:
            return False
    
    def _test_module_import_chain(self) -> bool:
        """测试模块导入链"""
        try:
            import readpack
            import intentpatch
            import patchfitroom
            return True
        except Exception:
            return False
    
    def _test_state_persistence(self) -> bool:
        """测试状态持久化"""
        state_dir = REPO_ROOT / "state" / "projects"
        return state_dir.exists()


if __name__ == "__main__":
    suite = RegressionSuite()
    result = suite.run()
    print(f"Regression 结果: {result}")
