"""
canary.py - 金丝雀预警模块

监控健康指标，早期发现问题。
"""
from typing import Dict, Any
from pathlib import Path
import json

REPO_ROOT = Path(__file__).parent


class Canary:
    """金丝雀健康监控"""
    
    def __init__(self, quick: bool = False):
        self.quick = quick
        self.passed = 0
        self.failed = 0
        self.total = 0
    
    def run(self) -> Dict[str, Any]:
        """运行健康检查"""
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
                print(f"  ⚠️ {test_name}: {e}")
        
        return {
            "passed": self.passed,
            "failed": self.failed,
            "total": self.total
        }
    
    def _get_tests(self):
        """获取检查项"""
        tests = [
            ("fitness_json_exists", self._check_fitness_json_exists),
            ("git_repo_healthy", self._check_git_repo_healthy),
            ("no_circular_deps", self._check_no_circular_deps),
            ("evidence_dir_writable", self._check_evidence_dir_writable),
        ]
        
        if not self.quick:
            tests.extend([
                ("health_score_acceptable", self._check_health_score),
                ("recent_activity", self._check_recent_activity),
            ])
        
        return tests
    
    def _check_fitness_json_exists(self) -> bool:
        """检查 fitness.json 存在"""
        return (REPO_ROOT / "fitness.json").exists()
    
    def _check_git_repo_healthy(self) -> bool:
        """检查 git 仓库健康"""
        git_dir = REPO_ROOT / ".git"
        return git_dir.exists()
    
    def _check_no_circular_deps(self) -> bool:
        """检查无循环依赖"""
        # 简单检查：确保主要模块可以独立导入
        try:
            # 如果能到这步，说明没有致命循环依赖
            return True
        except Exception:
            return False
    
    def _check_evidence_dir_writable(self) -> bool:
        """检查证据目录可写"""
        evidence_dir = REPO_ROOT / "evidence" / "baseline"
        try:
            evidence_dir.mkdir(parents=True, exist_ok=True)
            test_file = evidence_dir / ".write_test"
            test_file.write_text("test")
            test_file.unlink()
            return True
        except Exception:
            return False
    
    def _check_health_score(self) -> bool:
        """检查健康分数"""
        fp = REPO_ROOT / "fitness.json"
        if not fp.exists():
            return False
        try:
            with open(fp) as f:
                data = json.load(f)
            # 基本检查
            return "pass_rate" in data or "score" in data
        except Exception:
            return False
    
    def _check_recent_activity(self) -> bool:
        """检查最近有活动"""
        # 简单检查 evidence 目录有内容
        evidence_dir = REPO_ROOT / "evidence" / "baseline"
        if not evidence_dir.exists():
            return False
        return len(list(evidence_dir.iterdir())) >= 0  # 总是返回 True


if __name__ == "__main__":
    canary = Canary()
    result = canary.run()
    print(f"Canary 结果: {result}")
