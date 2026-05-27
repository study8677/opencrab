"""
CLI探测模块的测试用例
"""
import unittest
import json
from cli_probe import CLIProbe, CLIHealthReport

class TestCLIProbe(unittest.TestCase):
    
    def setUp(self):
        self.probe = CLIProbe(timeout=2)  # 短超时用于测试
    
    def test_probe_single_working_command(self):
        """测试单个正常工作的命令"""
        report = self.probe.probe_single("echo hello")
        
        self.assertEqual(report.exit_code, 0)
        self.assertIn("hello", report.stdout_snippet)
        self.assertFalse(report.has_json_output)  # echo 输出不是JSON
    
    def test_probe_single_json_command(self):
        """测试JSON输出命令"""
        # 使用 python -c 生成JSON输出
        report = self.probe.probe_single('python3 -c "import json; print(json.dumps({\'test\': 123}))"')
        
        self.assertEqual(report.exit_code, 0)
        self.assertTrue(report.has_json_output)
        self.assertEqual(report.json_shape, "dict")
        self.assertIn("test", report.json_keys)
    
    def test_probe_single_failing_command(self):
        """测试失败的命令"""
        report = self.probe.probe_single("nonexistent_command_12345")
        
        self.assertNotEqual(report.exit_code, 0)
        self.assertEqual(report.exit_code, -1)  # FileNotFoundError
        self.assertIn("not found", (report.first_error or "").lower())
    
    def test_probe_sample(self):
        """测试批量探测"""
        # 使用少量命令快速测试
        test_commands = ["echo test1", "echo test2", "ls --version"]
        reports = self.probe.probe_sample(test_commands)
        
        self.assertEqual(len(reports), 3)
        self.assertTrue(all(isinstance(r, CLIHealthReport) for r in reports))
    
    def test_health_score_calculation(self):
        """测试健康评分计算"""
        # 创建模拟报告
        reports = [
            CLIHealthReport("cmd1", 0, False, None, None, None, None, None),
            CLIHealthReport("cmd2", 1, False, None, None, None, None, None),
            CLIHealthReport("cmd3", 0, False, None, None, None, None, None),
            CLIHealthReport("cmd4", 0, False, None, None, None, None, None)
        ]
        
        score = self.probe._calculate_health_score(reports)
        self.assertEqual(score, 75.0)  # 3/4 = 75%
    
    def test_json_analysis(self):
        """测试JSON分析功能"""
        # 测试有效JSON
        has_json, shape, keys = self.probe._analyze_json_output('{"a": 1, "b": 2}')
        self.assertTrue(has_json)
        self.assertEqual(shape, "dict")
        self.assertEqual(sorted(keys), ["a", "b"])
        
        # 测试列表JSON
        has_json, shape, keys = self.probe._analyze_json_output('[1, 2, 3]')
        self.assertTrue(has_json)
        self.assertIn("list", shape)
        
        # 测试无效JSON
        has_json, shape, keys = self.probe._analyze_json_output('not json')
        self.assertFalse(has_json)
        self.assertIsNone(shape)
        self.assertIsNone(keys)

if __name__ == "__main__":
    unittest.main()
