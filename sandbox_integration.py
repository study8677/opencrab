"""
沙盒补丁集成模块 - 将沙盒功能集成到现有工作流
"""
from typing import Optional
from sandbox_patch import SandboxPatch, sandbox_patch_test
from patchcourse import PatchCourse
from evidence import Evidence, EvidenceType


class SandboxIntegration:
    """沙盒集成器"""
    
    def __init__(self):
        self.sandbox = SandboxPatch()
        self.patch_course = PatchCourse()
    
    def process_pr_patch(self, pr_url: str, patch_content: str) -> dict:
        """处理PR补丁"""
        return sandbox_patch_test(patch_content, f"pr:{pr_url}")
    
    def process_issue_patch(self, issue_id: str, patch_content: str) -> dict:
        """处理issue补丁"""
        return sandbox_patch_test(patch_content, f"issue:{issue_id}")
    
    def integrate_with_patchcourse(self, patch_data: dict) -> dict:
        """与patchcourse集成"""
        # 从patchcourse获取补丁
        patch_id = patch_data.get("id")
        if not patch_id:
            return {"error": "需要补丁ID"}
        
        # 运行沙盒测试
        sandbox_report = sandbox_patch_test(
            patch_data.get("content", ""),
            f"patchcourse:{patch_id}"
        )
        
        # 根据结果决定是否继续patchcourse流程
        if sandbox_report.get("status") == "accepted":
            # 继续正常流程
            return {
                "sandbox_passed": True,
                "sandbox_report": sandbox_report,
                "next_step": "proceed_to_patchcourse"
            }
        else:
            # 拒绝补丁
            return {
                "sandbox_passed": False,
                "sandbox_report": sandbox_report,
                "next_step": "reject_patch"
            }


# 便捷函数
def test_patch_with_sandbox(patch_content: str, source: str = "external") -> dict:
    """测试补丁是否通过沙盒"""
    return sandbox_patch_test(patch_content, source)


def integrate_pr_patch(pr_url: str, patch_content: str) -> dict:
    """集成PR补丁"""
    integrator = SandboxIntegration()
    return integrator.process_pr_patch(pr_url, patch_content)


def integrate_issue_patch(issue_id: str, patch_content: str) -> dict:
    """集成issue补丁"""
    integrator = SandboxIntegration()
    return integrator.process_issue_patch(issue_id, patch_content)


if __name__ == "__main__":
    # 示例用法
    print("沙盒补丁集成模块已加载")
    print("使用示例:")
    print("  from sandbox_integration import test_patch_with_sandbox")
    print("  result = test_patch_with_sandbox(patch_content, 'pr_url')")
