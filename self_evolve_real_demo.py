"""
自演化实战闭环演示：使用 triage × readpack × intentpatch × patchfitroom 完成一次真实代码改进。
本次目标：改进 readpack.py 中的 read_file 函数，添加错误处理和性能监控。
"""

import triage
import readpack
import intentpatch
import patchfitroom
import ast
import time
import traceback
from typing import Optional, Tuple

class SelfEvolveRealDemo:
    def __init__(self):
        self.target_file = "readpack.py"
        self.target_function = "read_file"
        self.improvement_intent = "添加文件读取错误处理和性能监控"
        
    def run(self):
        """执行完整的自演化闭环：诊断 -> 读取 -> 生成补丁 -> 验证 -> 回灌证据"""
        print("=== 自演化实战闭环开始 ===")
        
        # 1. triage：诊断问题，确定改进优先级
        priority, diagnosis = triage.triage_issue(
            file_path=self.target_file,
            issue_description="文件读取缺乏错误处理和性能监控",
            codebase=self._read_codebase()
        )
        print(f"诊断完成: 优先级={priority}, 诊断={diagnosis}")
        
        # 2. readpack：读取目标函数代码
        original_code, metadata = readpack.read_function(
            file_path=self.target_file,
            function_name=self.target_function,
            include_context=True
        )
        print(f"读取 {self.target_function} 函数完成，共 {len(original_code)} 行")
        
        # 3. intentpatch：根据意图生成补丁
        intent = intentpatch.parse_intent(self.improvement_intent)
        patch = intentpatch.generate_patch(
            original_code=original_code,
            intent=intent,
            constraints={"preserve_signature": True, "minimal_changes": True}
        )
        print(f"补丁生成完成，变更行数: {len(patch.changes)}")
        
        # 4. patchfitroom：验证补丁
        validation_result = patchfitroom.validate_patch(
            original_code=original_code,
            patch=patch,
            test_suite="quick_smoke",
            timeout=10
        )
        
        if validation_result.success:
            print("补丁验证通过！")
            # 5. 回灌证据
            self._evidence_feedback(patch, validation_result)
            # 6. 应用补丁（在安全模式下）
            self._apply_patch(patch)
            print("=== 自演化实战闭环完成 ===")
            return True
        else:
            print(f"补丁验证失败: {validation_result.errors}")
            return False
    
    def _read_codebase(self) -> dict:
        """读取代码库快照，用于诊断"""
        try:
            with open(self.target_file, 'r', encoding='utf-8') as f:
                code = f.read()
            return {self.target_file: code}
        except Exception as e:
            print(f"警告: 无法读取代码库 - {e}")
            return {}
    
    def _evidence_feedback(self, patch, validation_result):
        """回灌自演化证据"""
        evidence = {
            "timestamp": time.time(),
            "target": f"{self.target_file}::{self.target_function}",
            "intent": self.improvement_intent,
            "patch_size": len(patch.changes),
            "validation_passed": validation_result.success,
            "validation_time": validation_result.duration,
            "test_results": validation_result.test_results
        }
        
        # 保存证据到日志
        import json
        import os
        evidence_dir = "evidence/evolution_logs"
        os.makedirs(evidence_dir, exist_ok=True)
        
        timestamp_str = time.strftime("%Y%m%d_%H%M%S")
        evidence_file = f"{evidence_dir}/self_evolve_{timestamp_str}.json"
        
        with open(evidence_file, 'w', encoding='utf-8') as f:
            json.dump(evidence, f, indent=2, ensure_ascii=False)
        
        print(f"证据已回灌: {evidence_file}")
    
    def _apply_patch(self, patch):
        """安全应用补丁到目标文件"""
        try:
            # 读取原始文件
            with open(self.target_file, 'r', encoding='utf-8') as f:
                original_content = f.read()
            
            # 应用补丁
            new_content = intentpatch.apply_patch(original_content, patch)
            
            # 语法检查
            try:
                ast.parse(new_content)
                print("语法检查通过")
            except SyntaxError as e:
                print(f"警告: 补丁语法错误 - {e}")
                return False
            
            # 备份原文件
            backup_file = f"{self.target_file}.bak"
            with open(backup_file, 'w', encoding='utf-8') as f:
                f.write(original_content)
            
            # 写入新文件
            with open(self.target_file, 'w', encoding='utf-8') as f:
                f.write(new_content)
            
            print(f"补丁已应用到 {self.target_file}（备份: {backup_file}）")
            return True
            
        except Exception as e:
            print(f"应用补丁失败: {e}")
            traceback.print_exc()
            return False


if __name__ == "__main__":
    demo = SelfEvolveRealDemo()
    success = demo.run()
    exit(0 if success else 1)
