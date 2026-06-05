"""
arena.py - Arena 评测模块

提供基本的冒烟测试能力，验证核心功能可用性。
"""
from typing import Dict, Any
from pathlib import Path

REPO_ROOT = Path(__file__).parent


class Arena:
    """Arena 冒烟评测器"""
    
    def __init__(self, quick: bool = False):
        self.quick = quick
        self.passed = 0
        self.failed = 0
        self.total = 0
    
    def run(self) -> Dict[str, Any]:
        """运行冒烟测试"""
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
            ("crab_import", self._test_crab_import),
            ("readpack_import", self._test_readpack_import),
            ("intentpatch_import", self._test_intentpatch_import),
            ("patchfitroom_import", self._test_patchfitroom_import),
            ("fitness_json_exists", self._test_fitness_json_exists),
        ]
        
        if not self.quick:
            tests.extend([
                ("crab_basic_api", self._test_crab_basic_api),
                ("readpack_basic_api", self._test_readpack_basic_api),
            ])
        
        return tests
    
    def _test_crab_import(self) -> bool:
        try:
            import crab
            return True
        except Exception:
            return False
    
    def _test_readpack_import(self) -> bool:
        try:
            import readpack
            return True
        except Exception:
            return False
    
    def _test_intentpatch_import(self) -> bool:
        try:
            import intentpatch
            return True
        except Exception:
            return False
    
    def _test_patchfitroom_import(self) -> bool:
        try:
            import patchfitroom
            return True
        except Exception:
            return False
    
    def _test_fitness_json_exists(self) -> bool:
        return (REPO_ROOT / "fitness.json").exists()
    
    def _test_crab_basic_api(self) -> bool:
        try:
            import crab
            return hasattr(crab, '__version__') or hasattr(crab, 'version')
        except Exception:
            return False
    
    def _test_readpack_basic_api(self) -> bool:
        try:
            import readpack
            return len(dir(readpack)) > 0
        except Exception:
            return False


if __name__ == "__main__":
    arena = Arena()
    result = arena.run()
    print(f"Arena 结果: {result}")
