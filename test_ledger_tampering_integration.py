"""
账本篡改联动实跑测试
模拟伪造evidence/audit历史记录，验证ledgerseal报警、releasegate拦截、recovery修复路径
"""
import json
import os
import tempfile
from pathlib import Path

def create_tampered_evidence(tamper_type="hash_mismatch"):
    """创建一条被篡改的evidence记录"""
    evidence = {
        "id": "ev_tampered_001",
        "timestamp": "2024-01-15T10:30:00Z",
        "action": "code_modification",
        "actor": "openai/gpt-4",
        "integrity": {
            "content_hash": "a1b2c3d4e5f6",
            "timestamp_hash": "f6e5d4c3b2a1",
            "chain_hash": "1234567890abcdef"
        }
    }
    
    # 根据篡改类型修改证据
    if tamper_type == "hash_mismatch":
        # 篡改哈希值
        evidence["integrity"]["content_hash"] = "tampered_hash_001"
        evidence["integrity"]["chain_hash"] = "tampered_chain_001"
    elif tamper_type == "timestamp_anomaly":
        # 篡改时间戳
        evidence["timestamp"] = "2025-01-01T00:00:00Z"  # 未来时间
    elif tamper_type == "missing_fields":
        # 缺失关键字段
        del evidence["integrity"]
        del evidence["actor"]
    
    return evidence

def create_audit_trail(evidence_record):
    """创建包含篡改记录的审计轨迹"""
    audit_trail = [
        {
            "id": "audit_001",
            "timestamp": "2024-01-14T09:00:00Z",
            "action": "system_startup",
            "integrity": {"valid": True}
        },
        {
            "id": "audit_002", 
            "timestamp": "2024-01-14T12:00:00Z",
            "action": "configuration_change",
            "integrity": {"valid": True}
        },
        evidence_record,  # 被篡改的记录
        {
            "id": "audit_004",
            "timestamp": "2024-01-16T08:00:00Z",
            "action": "normal_operation",
            "integrity": {"valid": True}
        }
    ]
    return audit_trail

def save_to_temp_file(data, filename):
    """保存数据到临时文件"""
    temp_dir = tempfile.mkdtemp()
    filepath = os.path.join(temp_dir, filename)
    with open(filepath, 'w') as f:
        json.dump(data, f, indent=2)
    return filepath

def test_ledgerseal_detection():
    """测试ledgerseal的检测能力"""
    print("=== 测试1: Ledgerseal检测能力 ===")
    
    # 创建篡改证据
    evidence = create_tampered_evidence("hash_mismatch")
    audit_trail = create_audit_trail(evidence)
    
    # 保存到文件
    evidence_path = save_to_temp_file(evidence, "tampered_evidence.json")
    audit_path = save_to_temp_file(audit_trail, "audit_trail.json")
    
    print(f"创建篡改证据文件: {evidence_path}")
    print(f"创建审计轨迹文件: {audit_path}")
    
    # 这里假设ledgerseal模块存在并能检测篡改
    # 实际测试中需要调用ledgerseal.verify_evidence()或类似函数
    print("预期结果: ledgerseal应该报警检测到哈希不匹配")
    print("预期结果: ledgerseal应该标记该记录为可疑")
    
    return evidence_path, audit_path

def test_releasegate_blocking():
    """测试releasegate的拦截能力"""
    print("\n=== 测试2: Releasegate拦截能力 ===")
    
    # 模拟发布场景
    release_manifest = {
        "version": "1.2.0",
        "timestamp": "2024-01-15T15:00:00Z",
        "changes": ["feature_x", "fix_y"],
        "evidence_references": ["ev_tampered_001"]
    }
    
    # 保存发布清单
    manifest_path = save_to_temp_file(release_manifest, "release_manifest.json")
    print(f"创建发布清单: {manifest_path}")
    
    print("预期结果: releasegate应该检测到引用的证据已被标记为可疑")
    print("预期结果: releasegate应该阻止此次发布")
    print("预期结果: releasegate应该返回拦截原因和需要审核的证据列表")
    
    return manifest_path

def test_recovery_suggestions():
    """测试recovery的修复路径建议"""
    print("\n=== 测试3: Recovery修复路径建议 ===")
    
    # 模拟需要恢复的场景
    recovery_context = {
        "incident_type": "integrity_failure",
        "affected_records": ["ev_tampered_001"],
        "detection_time": "2024-01-15T14:30:00Z",
        "system_state": "partially_compromised"
    }
    
    # 保存恢复上下文
    context_path = save_to_temp_file(recovery_context, "recovery_context.json")
    print(f"创建恢复上下文: {context_path}")
    
    print("预期结果: recovery应该建议回滚到最近的干净状态")
    print("预期结果: recovery应该建议重新审计所有相关记录")
    print("预期结果: recovery应该提供具体的修复步骤序列")

def run_integration_test():
    """运行完整集成测试"""
    print("开始账本篡改联动实跑测试\n")
    
    # 阶段1: 测试ledgerseal检测
    evidence_path, audit_path = test_ledgerseal_detection()
    
    # 阶段2: 测试releasegate拦截
    manifest_path = test_releasegate_blocking()
    
    # 阶段3: 测试recovery建议
    test_recovery_suggestions()
    
    print("\n=== 测试总结 ===")
    print("1. 创建了被篡改的证据记录 (哈希不匹配)")
    print("2. 创建了包含篡改记录的审计轨迹")
    print("3. 模拟了包含可疑证据的发布清单")
    print("4. 创建了恢复上下文")
    print("\n下一步: 调用实际的ledgerseal, releasegate, recovery模块进行验证")
    
    return {
        "evidence_path": evidence_path,
        "audit_path": audit_path,
        "manifest_path": manifest_path
    }

if __name__ == "__main__":
    # 直接运行集成测试
    paths = run_integration_test()
    
    # 尝试调用实际模块
    print("\n尝试导入实际模块...")
    try:
        import ledgerseal
        print("✓ ledgerseal模块导入成功")
        
        # 假设的ledgerseal接口
        if hasattr(ledgerseal, 'verify_evidence'):
            evidence = json.load(open(paths["evidence_path"]))
            result = ledgerseal.verify_evidence(evidence)
            print(f"ledgerseal验证结果: {result}")
        else:
            print("  ledgerseal模块缺少verify_evidence方法")
            
    except ImportError as e:
        print(f"✗ ledgerseal导入失败: {e}")
    
    try:
        import releasegate
        print("✓ releasegate模块导入成功")
        
        # 假设的releasegate接口
        if hasattr(releasegate, 'check_release'):
            manifest = json.load(open(paths["manifest_path"]))
            result = releasegate.check_release(manifest)
            print(f"releasegate检查结果: {result}")
        else:
            print("  releasegate模块缺少check_release方法")
            
    except ImportError as e:
        print(f"✗ releasegate导入失败: {e}")
    
    try:
        import recovery
        print("✓ recovery模块导入成功")
        
        # 假设的recovery接口
        if hasattr(recovery, 'suggest_recovery'):
            context = {
                "incident_type": "integrity_failure",
                "affected_records": ["ev_tampered_001"]
            }
            suggestions = recovery.suggest_recovery(context)
            print(f"recovery建议: {suggestions}")
        else:
            print("  recovery模块缺少suggest_recovery方法")
            
    except ImportError as e:
        print(f"✗ recovery导入失败: {e}")
    
    print("\n集成测试完成")
