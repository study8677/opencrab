#!/usr/bin/env python3
"""
领地生命线模块端到端冒烟测试。
检查 audit / memory / evidence / planner / trustscore 能否基本跑通。
"""

import sys
import traceback

def test_audit():
    """测试 audit 模块"""
    try:
        from audit import AuditManager
        manager = AuditManager()
        # 测试记录和读取
        entry = {"action": "test", "timestamp": 0}
        manager.log(entry)
        entries = manager.recent(1)
        assert len(entries) >= 1, "audit.recent 未返回记录"
        print("✓ audit 模块基本功能正常")
        return True
    except Exception as e:
        print(f"✗ audit 模块测试失败: {e}")
        traceback.print_exc()
        return False

def test_memory():
    """测试 memory 模块"""
    try:
        from memory import Memory
        memory = Memory()
        # 测试写入和读取
        memory.remember("test_key", "test_value")
        value = memory.recall("test_key")
        assert value == "test_value", f"memory.recall 返回错误值: {value}"
        # 测试遗忘
        memory.forget("test_key")
        assert memory.recall("test_key") is None, "memory.forget 失败"
        print("✓ memory 模块基本功能正常")
        return True
    except Exception as e:
        print(f"✗ memory 模块测试失败: {e}")
        traceback.print_exc()
        return False

def test_evidence():
    """测试 evidence 模块"""
    try:
        from evidence import EvidenceStore
        store = EvidenceStore()
        # 测试添加和检索
        evidence = {"type": "test", "content": "test evidence"}
        ev_id = store.add(evidence)
        retrieved = store.get(ev_id)
        assert retrieved is not None, "evidence.get 返回 None"
        assert retrieved["type"] == "test", "evidence 内容不匹配"
        # 测试过期检查（假设实现 exists 和 is_fresh）
        if hasattr(store, 'exists'):
            assert store.exists(ev_id), "evidence.exists 失败"
        print("✓ evidence 模块基本功能正常")
        return True
    except Exception as e:
        print(f"✗ evidence 模块测试失败: {e}")
        traceback.print_exc()
        return False

def test_planner():
    """测试 planner 模块"""
    try:
        # 尝试多种导入方式
        try:
            from planner import Planner, PlanState
        except ImportError:
            from planner import Planner
            # 如果 PlanState 不可导入，使用字符串替代
            PlanState = None
        
        planner = Planner()
        # 测试创建简单计划
        goal = "测试目标"
        plan = planner.create_plan(goal)
        assert plan is not None, "planner.create_plan 返回 None"
        # 测试计划状态检查
        if PlanState:
            assert isinstance(plan.state, PlanState), "计划状态类型错误"
        print("✓ planner 模块基本功能正常")
        return True
    except Exception as e:
        print(f"✗ planner 模块测试失败: {e}")
        traceback.print_exc()
        return False

def test_trustscore():
    """测试 trustscore 模块"""
    try:
        from trustscore import TrustScore
        scorer = TrustScore()
        # 测试评分计算
        score = scorer.calculate("test_entity", {"metrics": [1.0, 0.8, 0.9]})
        assert isinstance(score, (int, float)), f"trustscore.calculate 返回非数字: {score}"
        assert 0 <= score <= 1, f"分数超出范围: {score}"
        print("✓ trustscore 模块基本功能正常")
        return True
    except Exception as e:
        print(f"✗ trustscore 模块测试失败: {e}")
        traceback.print_exc()
        return False

def main():
    """运行所有测试"""
    tests = [
        ("audit", test_audit),
        ("memory", test_memory),
        ("evidence", test_evidence),
        ("planner", test_planner),
        ("trustscore", test_trustscore),
    ]
    
    results = {}
    for name, test_func in tests:
        print(f"\n测试 {name} 模块...")
        results[name] = test_func()
    
    print("\n" + "="*50)
    print("测试结果汇总:")
    for name, passed in results.items():
        status = "✓ 通过" if passed else "✗ 失败"
        print(f"  {name}: {status}")
    
    all_passed = all(results.values())
    print(f"\n总结: {'所有测试通过' if all_passed else '存在失败测试'}")
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
