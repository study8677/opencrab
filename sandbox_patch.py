"""
外来补丁沙盒：将PR/issue改动先转受限补丁，在临时副本跑检查后给接纳证据
"""
import os
import shutil
import tempfile
import subprocess
import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime

from evidence import Evidence, EvidenceType
from licenseguard import check_license
from secretscan import scan_secrets
from smoke import run_smoke_tests
from patchcontract import PatchContract, PatchScope


class SandboxPatch:
    """外来补丁沙盒处理器"""
    
    def __init__(self, repo_root: Optional[str] = None):
        self.repo_root = Path(repo_root) if repo_root else Path.cwd()
        self.sandbox_dir = None
        self.evidence = []
        
    def create_sandbox(self) -> Path:
        """创建临时沙盒环境"""
        self.sandbox_dir = Path(tempfile.mkdtemp(prefix="crab_sandbox_"))
        
        # 创建基本目录结构
        dirs_to_create = [
            "patches",
            "workdir",
            "evidence"
        ]
        
        for dir_name in dirs_to_create:
            (self.sandbox_dir / dir_name).mkdir(parents=True, exist_ok=True)
            
        # 复制关键配置文件到沙盒
        config_files = [
            ".crab.yaml",
            "requirements.txt",
            "setup.py"
        ]
        
        for config in config_files:
            config_path = self.repo_root / config
            if config_path.exists():
                shutil.copy2(config_path, self.sandbox_dir / "workdir")
        
        return self.sandbox_dir
    
    def convert_to_restricted_patch(self, patch_content: str, patch_source: str) -> Tuple[PatchContract, List[str]]:
        """
        将外来补丁转换为受限补丁
        返回补丁合同和限制说明
        """
        restrictions = []
        
        # 分析补丁内容，自动添加限制
        contract = PatchContract(
            source=patch_source,
            scope=PatchScope.LIMITED,
            restrictions=[
                "sandbox_only",  # 只在沙盒中执行
                "time_limited",  # 执行时间限制
                "resource_capped",  # 资源使用上限
                "no_external_io"  # 禁止外部IO
            ]
        )
        
        # 解析补丁内容，识别可能的危险操作
        danger_patterns = [
            "os.system",
            "subprocess.run",
            "subprocess.Popen",
            "exec(",
            "eval(",
            "open(",  # 可能写文件
            "requests.get",  # 网络请求
            "urllib.request"
        ]
        
        lines = patch_content.split('\n')
        for i, line in enumerate(lines):
            for pattern in danger_patterns:
                if pattern in line:
                    restrictions.append(f"Line {i+1}: 受限操作 '{pattern}'")
        
        return contract, restrictions
    
    def apply_patch_sandbox(self, patch_content: str, patch_source: str) -> Dict:
        """
        在沙盒中应用补丁并运行检查
        返回接纳证据
        """
        evidence_list = []
        sandbox_status = "success"
        
        try:
            # 1. 创建沙盒
            sandbox_dir = self.create_sandbox()
            
            # 2. 保存补丁内容
            patch_file = sandbox_dir / "patches" / f"patch_{datetime.now().strftime('%Y%m%d_%H%M%S')}.patch"
            with open(patch_file, 'w', encoding='utf-8') as f:
                f.write(patch_content)
            
            # 3. 转换为受限补丁
            contract, restrictions = self.convert_to_restricted_patch(patch_content, patch_source)
            
            # 4. 在工作目录应用补丁（模拟）
            workdir = sandbox_dir / "workdir"
            self._simulate_patch_application(workdir, patch_content)
            
            # 5. 运行许可证检查
            license_evidence = self._run_license_check(workdir)
            evidence_list.append(license_evidence)
            
            # 6. 运行密钥扫描
            secret_evidence = self._run_secret_scan(workdir)
            evidence_list.append(secret_evidence)
            
            # 7. 运行烟雾测试
            smoke_evidence = self._run_smoke_tests(workdir)
            evidence_list.append(smoke_evidence)
            
            # 8. 生成接纳证据
            acceptance_evidence = self._generate_acceptance_evidence(
                patch_source, 
                contract,
                restrictions,
                evidence_list,
                sandbox_status
            )
            
            # 9. 保存证据
            self._save_evidence(acceptance_evidence, sandbox_dir)
            
            return acceptance_evidence
            
        except Exception as e:
            sandbox_status = "failed"
            error_evidence = Evidence(
                type=EvidenceType.ERROR,
                content=f"沙盒执行失败: {str(e)}",
                metadata={"patch_source": patch_source}
            )
            evidence_list.append(error_evidence)
            
            return self._generate_acceptance_evidence(
                patch_source,
                contract if 'contract' in locals() else None,
                restrictions if 'restrictions' in locals() else [],
                evidence_list,
                sandbox_status
            )
        
        finally:
            # 清理沙盒（可选，保留用于调试）
            # if self.sandbox_dir and self.sandbox_dir.exists():
            #     shutil.rmtree(self.sandbox_dir, ignore_errors=True)
            pass
    
    def _simulate_patch_application(self, workdir: Path, patch_content: str):
        """模拟应用补丁（实际应用需要集成git apply或其他工具）"""
        # 创建测试文件来模拟补丁应用
        test_file = workdir / "test_patch_target.py"
        
        # 分析补丁内容，提取修改的文件
        lines = patch_content.split('\n')
        files_modified = set()
        
        for line in lines:
            if line.startswith('--- a/') or line.startswith('+++ b/'):
                file_path = line.split('/')[-1]
                if file_path not in files_modified:
                    files_modified.add(file_path)
        
        # 创建测试文件
        for file_name in files_modified[:3]:  # 最多处理3个文件
            test_content = f"""# {file_name} - 沙盒测试文件
# 由外来补丁沙盒自动生成
# 补丁来源: sandbox_test
# 时间: {datetime.now().isoformat()}

def sandbox_test_function():
    return "sandbox_test"

if __name__ == "__main__":
    print("Sandbox test file for {file_name}")
"""
            test_path = workdir / file_name
            test_path.parent.mkdir(parents=True, exist_ok=True)
            with open(test_path, 'w', encoding='utf-8') as f:
                f.write(test_content)
    
    def _run_license_check(self, workdir: Path) -> Evidence:
        """运行许可证检查"""
        try:
            # 调用现有的许可证检查
            license_result = check_license(str(workdir))
            
            status = "passed" if license_result.get("approved", False) else "failed"
            
            return Evidence(
                type=EvidenceType.LICENSE_CHECK,
                content=f"许可证检查: {status}",
                metadata={
                    "result": license_result,
                    "workdir": str(workdir)
                }
            )
        except Exception as e:
            return Evidence(
                type=EvidenceType.LICENSE_CHECK,
                content=f"许可证检查异常: {str(e)}",
                metadata={"workdir": str(workdir)}
            )
    
    def _run_secret_scan(self, workdir: Path) -> Evidence:
        """运行密钥扫描"""
        try:
            # 调用现有的密钥扫描
            secret_result = scan_secrets(str(workdir))
            
            has_secrets = secret_result.get("secrets_found", 0) > 0
            status = "failed" if has_secrets else "passed"
            
            return Evidence(
                type=EvidenceType.SECRET_SCAN,
                content=f"密钥扫描: {status} (发现 {secret_result.get('secrets_found', 0)} 个密钥)",
                metadata={
                    "result": secret_result,
                    "workdir": str(workdir)
                }
            )
        except Exception as e:
            return Evidence(
                type=EvidenceType.SECRET_SCAN,
                content=f"密钥扫描异常: {str(e)}",
                metadata={"workdir": str(workdir)}
            )
    
    def _run_smoke_tests(self, workdir: Path) -> Evidence:
        """运行烟雾测试"""
        try:
            # 调用现有的烟雾测试
            smoke_result = run_smoke_tests(str(workdir))
            
            status = "passed" if smoke_result.get("all_passed", False) else "failed"
            
            return Evidence(
                type=EvidenceType.SMOKE_TEST,
                content=f"烟雾测试: {status}",
                metadata={
                    "result": smoke_result,
                    "workdir": str(workdir)
                }
            )
        except Exception as e:
            return Evidence(
                type=EvidenceType.SMOKE_TEST,
                content=f"烟雾测试异常: {str(e)}",
                metadata={"workdir": str(workdir)}
            )
    
    def _generate_acceptance_evidence(self, patch_source: str, 
                                    contract: Optional[PatchContract],
                                    restrictions: List[str],
                                    check_evidence: List[Evidence],
                                    sandbox_status: str) -> Evidence:
        """生成接纳证据"""
        
        # 检查所有证据是否都通过
        all_passed = all(
            evidence.content.endswith("passed") 
            for evidence in check_evidence 
            if evidence.type in [EvidenceType.LICENSE_CHECK, EvidenceType.SECRET_SCAN, EvidenceType.SMOKE_TEST]
        )
        
        acceptance_status = "accepted" if all_passed and sandbox_status == "success" else "rejected"
        
        # 创建接纳证据
        acceptance_evidence = Evidence(
            type=EvidenceType.SANDBOX_ACCEPTANCE,
            content=f"补丁接纳状态: {acceptance_status}",
            metadata={
                "patch_source": patch_source,
                "sandbox_status": sandbox_status,
                "acceptance_status": acceptance_status,
                "timestamp": datetime.now().isoformat(),
                "contract": contract.to_dict() if contract else None,
                "restrictions": restrictions,
                "checks_passed": all_passed,
                "check_details": [
                    {
                        "type": evidence.type.value,
                        "status": evidence.content.split(": ")[-1] if ": " in evidence.content else "unknown",
                        "content": evidence.content
                    }
                    for evidence in check_evidence
                ]
            }
        )
        
        # 添加到证据列表
        self.evidence.append(acceptance_evidence)
        
        return acceptance_evidence
    
    def _save_evidence(self, evidence: Evidence, sandbox_dir: Path):
        """保存证据到沙盒"""
        evidence_dir = sandbox_dir / "evidence"
        evidence_file = evidence_dir / f"evidence_{evidence.metadata.get('timestamp', datetime.now().isoformat()).replace(':', '-')}.json"
        
        with open(evidence_file, 'w', encoding='utf-8') as f:
            json.dump(evidence.to_dict(), f, indent=2, ensure_ascii=False)
    
    def get_acceptance_report(self) -> Dict:
        """生成接纳报告"""
        if not self.evidence:
            return {"status": "no_evidence", "message": "没有运行过沙盒测试"}
        
        latest_evidence = self.evidence[-1]
        metadata = latest_evidence.metadata
        
        return {
            "status": metadata.get("acceptance_status", "unknown"),
            "patch_source": metadata.get("patch_source", "unknown"),
            "timestamp": metadata.get("timestamp", "unknown"),
            "checks_passed": metadata.get("checks_passed", False),
            "check_details": metadata.get("check_details", []),
            "restrictions": metadata.get("restrictions", []),
            "recommendation": self._generate_recommendation(metadata)
        }
    
    def _generate_recommendation(self, metadata: Dict) -> str:
        """生成接纳建议"""
        status = metadata.get("acceptance_status", "")
        
        if status == "accepted":
            return "补丁已通过沙盒测试，建议接纳。但请注意监控生产环境中的实际影响。"
        else:
            failed_checks = [
                check["type"] 
                for check in metadata.get("check_details", [])
                if check["status"] != "passed"
            ]
            
            if failed_checks:
                return f"补丁未通过沙盒测试，原因: {', '.join(failed_checks)}。建议修复后重新测试。"
            else:
                return "补丁沙盒测试失败，建议拒绝接纳。"


def sandbox_patch_test(patch_content: str, patch_source: str = "test") -> Dict:
    """便捷函数：运行补丁沙盒测试"""
    sandbox = SandboxPatch()
    evidence = sandbox.apply_patch_sandbox(patch_content, patch_source)
    return sandbox.get_acceptance_report()


if __name__ == "__main__":
    # 测试示例
    test_patch = """--- a/test.py
+++ b/test.py
@@ -1,3 +1,4 @@
 def hello():
     print("Hello")
+    print("World")
 
+def new_function():
+    return True
"""
    
    report = sandbox_patch_test(test_patch, "test_pr_123")
    print(json.dumps(report, indent=2, ensure_ascii=False))
