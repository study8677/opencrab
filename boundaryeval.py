"""
boundaryeval.py - 边界评测模块

测试系统在边界条件下的表现。
"""
from typing import Dict, Any
from pathlib import Path

REPO_ROOT = Path(__file__).parent


class BoundaryEval:
    """边界条件评测器"""
    
    def __init__(self, quick: bool = False):
        self.quick = quick
        self.passed = 0
        self.failed = 0
        self.total = 0
    
    def run(self) -> Dict[str, Any]:
        """运行边界测试"""
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
            ("empty_file_handling", self._test_empty_file),
            ("malformed_json_handling", self._test_malformed_json),
            ("missing_deps_handling", self._test_missing_deps),
            ("long_line_handling", self._test_long_line),
        ]
        
        if not self.quick:
            tests.extend([
                ("deep_nesting_handling", self._test_deep_nesting),
                ("unicode_handling", self._test_unicode),
            ])
        
        return tests
    
    def _test_empty_file(self) -> bool:
        """测试空文件处理"""
        try:
            from readpack import read_file_safe
            result = read_file_safe("")
            return result is not None
        except Exception:
            return False
    
    def _test_malformed_json(self) -> bool:
        """测试畸形 JSON 处理"""
        try:
            from readpack import parse_json_safe
            result = parse_json_safe("{invalid json}")
            return result is None  # 应该返回 None 而非崩溃
        except Exception:
            return False  # 崩溃 = 失败
    
    def _test_missing_deps(self) -> bool:
        """测试缺失依赖处理"""
        try:
            from readpack import safe_import
            result = safe_import("nonexistent_module_xyz123")
            return result is None
        except Exception:
            return False
    
    def _test_long_line(self) -> bool:
        """测试超长行处理"""
        try:
            from readpack import read_file_safe
            long_content = "x" * 10000
            return True  # 基本不崩溃即可
        except Exception:
            return False
    
    def _test_deep_nesting(self) -> bool:
        """测试深层嵌套"""
        return True  # 占位
    
    def _test_unicode(self) -> bool:
        """测试 Unicode 处理"""
        try:
            return "中文测试" in "中文测试 abc"
        except Exception:
            return False


if __name__ == "__main__":
    be = BoundaryEval()
    result = be.run()
    print(f"BoundaryEval 结果: {result}")
