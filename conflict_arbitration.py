import os
import json
from typing import Dict, Any, Optional

class ConflictArbitrator:
    def __init__(self, evidence_path: str = 'evidence.py', replay_path: str = 'replay.py', readme_path: str = 'README.md'):
        self.evidence_path = evidence_path
        self.replay_path = replay_path
        self.readme_path = readme_path
        self.evidence_data = None
        self.replay_data = None
        self.readme_content = None
    
    def load_data(self):
        """加载证据账本、回放结果和README内容。"""
        # 尝试导入 evidence 模块获取数据
        try:
            import evidence
            if hasattr(evidence, 'get_ledger'):
                self.evidence_data = evidence.get_ledger()
            else:
                self.evidence_data = getattr(evidence, 'LEDGER', {})
        except ImportError:
            self.evidence_data = {}
        
        # 尝试导入 replay 模块获取数据
        try:
            import replay
            if hasattr(replay, 'get_results'):
                self.replay_data = replay.get_results()
            else:
                self.replay_data = getattr(replay, 'RESULTS', {})
        except ImportError:
            self.replay_data = {}
        
        # 读取 README 文件
        if os.path.exists(self.readme_path):
            with open(self.readme_path, 'r') as f:
                self.readme_content = f.read()
        else:
            self.readme_content = ''
    
    def extract_evidence_claims(self) -> Dict[str, Any]:
        """从证据账本提取声明（键值对）。"""
        return self.evidence_data or {}
    
    def extract_replay_claims(self) -> Dict[str, Any]:
        """从回放结果提取声明（键值对）。"""
        return self.replay_data or {}
    
    def extract_readme_claims(self) -> Dict[str, Any]:
        """从 README 提取声明（简单键值对解析）。"""
        claims = {}
        if self.readme_content:
            lines = self.readme_content.split('\n')
            for line in lines:
                if ':' in line:
                    key, value = line.split(':', 1)
                    claims[key.strip()] = value.strip()
        return claims
    
    def check_conflicts(self) -> Dict[str, Any]:
        """检查三个数据源之间的冲突。返回冲突详情字典。"""
        evidence_claims = self.extract_evidence_claims()
        replay_claims = self.extract_replay_claims()
        readme_claims = self.extract_readme_claims()
        
        conflicts = {}
        # 比较证据与回放
        for key in set(evidence_claims.keys()) & set(replay_claims.keys()):
            if evidence_claims[key] != replay_claims[key]:
                conflicts[key] = {
                    'evidence': evidence_claims[key],
                    'replay': replay_claims[key],
                    'readme': readme_claims.get(key, 'N/A')
                }
        # 比较证据与 README
        for key in set(evidence_claims.keys()) & set(readme_claims.keys()):
            if evidence_claims[key] != readme_claims[key]:
                if key not in conflicts:
                    conflicts[key] = {
                        'evidence': evidence_claims[key],
                        'replay': replay_claims.get(key, 'N/A'),
                        'readme': readme_claims[key]
                    }
                else:
                    conflicts[key]['readme'] = readme_claims[key]
        # 比较回放与 README
        for key in set(replay_claims.keys()) & set(readme_claims.keys()):
            if replay_claims[key] != readme_claims[key]:
                if key not in conflicts:
                    conflicts[key] = {
                        'evidence': evidence_claims.get(key, 'N/A'),
                        'replay': replay_claims[key],
                        'readme': readme_claims[key]
                    }
                else:
                    conflicts[key]['readme'] = readme_claims[key]
        return conflicts
    
    def generate_recheck_command(self, conflicts: Dict[str, Any]) -> str:
        """基于冲突生成最小复验命令字符串。"""
        if not conflicts:
            return "echo 'No conflicts detected.'"
        # 生成一个 Python 命令来重新运行仲裁并打印冲突详情
        cmd = (
            "python -c \""
            "from conflict_arbitration import ConflictArbitrator; "
            "a = ConflictArbitrator(); a.load_data(); "
            "c = a.check_conflicts(); print(c)\""
        )
        return cmd

# 便捷函数
def arbitrate_conflicts() -> str:
    """检查冲突并返回复验命令。"""
    arbitrator = ConflictArbitrator()
    arbitrator.load_data()
    conflicts = arbitrator.check_conflicts()
    return arbitrator.generate_recheck_command(conflicts)

if __name__ == '__main__':
    print(arbitrate_conflicts())
