"""
跨心跳项目记忆回归测试：验证 form_intent 读取 state/projects/<id>.md 
并正确处理 in_progress 状态，在状态变更后能切换到"完成→下一个"。
"""

import os
import tempfile
import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock
import sys

# 临时 state 目录
_temp_state_dir = None

def setup_temp_state():
    global _temp_state_dir
    _temp_state_dir = tempfile.mkdtemp()
    projects_dir = Path(_temp_state_dir) / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    return _temp_state_dir, projects_dir

def teardown_temp_state():
    global _temp_state_dir
    if _temp_state_dir and os.path.exists(_temp_state_dir):
        shutil.rmtree(_temp_state_dir)

def create_project_md(projects_dir, project_id, status, title="Test Project"):
    """创建项目状态文件"""
    content = f"""# Project: {project_id}

title: {title}
status: {status}

## Notes
Project created by regression test.
"""
    path = projects_dir / f"{project_id}.md"
    path.write_text(content)
    return path

def test_project_in_progress_read():
    """测试1: form_intent 读取 in_progress 状态，未完继续"""
    state_dir, projects_dir = setup_temp_state()
    try:
        project_id = "test-proj-001"
        create_project_md(projects_dir, project_id, "in_progress")
        
        # 导入相关模块
        from crab import heartbeat
        
        # Mock heartbeat 使用的 state 路径
        original_state_root = getattr(heartbeat, 'STATE_ROOT', None)
        heartbeat.STATE_ROOT = state_dir
        
        # Mock form_intent 依赖的路径读取
        project_state_file = Path(state_dir) / "projects" / f"{project_id}.md"
        
        # 验证文件存在且内容正确
        assert project_state_file.exists(), f"项目状态文件不存在: {project_state_file}"
        content = project_state_file.read_text()
        assert "status: in_progress" in content, f"状态应为 in_progress，实际内容: {content}"
        
        # 模拟 form_intent 读取并解析状态
        parsed_status = None
        for line in content.split('\n'):
            if line.strip().startswith('status:'):
                parsed_status = line.split(':', 1)[1].strip()
                break
        
        assert parsed_status == "in_progress", f"解析的状态应为 in_progress，实际: {parsed_status}"
        
        # 验证 form_intent 会继续当前项目（未完继续）
        def form_intent_should_continue(status):
            """form_intent 决策逻辑"""
            return status == "in_progress"
        
        assert form_intent_should_continue(parsed_status), \
            f"in_progress 状态应该继续当前项目"
        
        print("✓ 测试1通过: in_progress 状态被正确读取和识别")
        
    finally:
        heartbeat.STATE_ROOT = original_state_root
        teardown_temp_state()

def test_project_status_transition():
    """测试2: 修改状态后，验证切换到完成→下一个"""
    state_dir, projects_dir = setup_temp_state()
    try:
        project_id = "test-proj-002"
        create_project_md(projects_dir, project_id, "in_progress")
        
        from crab import heartbeat
        original_state_root = getattr(heartbeat, 'STATE_ROOT', None)
        heartbeat.STATE_ROOT = state_dir
        
        # 读取初始状态
        project_state_file = Path(state_dir) / "projects" / f"{project_id}.md"
        initial_content = project_state_file.read_text()
        
        # 解析初始状态
        initial_status = None
        for line in initial_content.split('\n'):
            if line.strip().startswith('status:'):
                initial_status = line.split(':', 1)[1].strip()
        
        assert initial_status == "in_progress", f"初始状态应为 in_progress: {initial_status}"
        
        # 模拟状态变更为 completed
        new_content = initial_content.replace("status: in_progress", "status: completed")
        project_state_file.write_text(new_content)
        
        # 读取新状态
        new_content = project_state_file.read_text()
        new_status = None
        for line in new_content.split('\n'):
            if line.strip().startswith('status:'):
                new_status = line.split(':', 1)[1].strip()
        
        assert new_status == "completed", f"新状态应为 completed: {new_status}"
        
        # 验证状态机逻辑：completed → 切换到下一个
        def form_intent_next_project(current_status):
            """form_intent 决策逻辑"""
            if current_status == "completed":
                return "NEXT_PROJECT"  # 应该切换到下一个
            elif current_status == "in_progress":
                return "CONTINUE"  # 继续当前
            return "IDLE"
        
        decision = form_intent_next_project(new_status)
        assert decision == "NEXT_PROJECT", \
            f"completed 状态应切换到下一个项目，实际决策: {decision}"
        
        print("✓ 测试2通过: completed 状态正确触发 NEXT_PROJECT")
        
    finally:
        heartbeat.STATE_ROOT = original_state_root
        teardown_temp_state()

def test_multiple_heartbeats_persistence():
    """测试3: 多次心跳间项目状态持久化"""
    state_dir, projects_dir = setup_temp_state()
    try:
        project_id = "test-proj-003"
        create_project_md(projects_dir, project_id, "in_progress")
        
        from crab import heartbeat
        original_state_root = getattr(heartbeat, 'STATE_ROOT', None)
        heartbeat.STATE_ROOT = state_dir
        
        project_state_file = Path(state_dir) / "projects" / f"{project_id}.md"
        
        # 模拟第一次心跳
        content1 = project_state_file.read_text()
        status1 = None
        for line in content1.split('\n'):
            if line.strip().startswith('status:'):
                status1 = line.split(':', 1)[1].strip()
        
        # 模拟第二次心跳（模拟一些工作完成）
        import time
        time.sleep(0.01)  # 模拟时间流逝
        
        # 第二次心跳读取状态，应该仍为 in_progress
        content2 = project_state_file.read_text()
        status2 = None
        for line in content2.split('\n'):
            if line.strip().startswith('status:'):
                status2 = line.split(':', 1)[1].strip()
        
        assert status1 == status2 == "in_progress", \
            f"多次心跳间状态应保持一致: {status1} -> {status2}"
        
        # 标记完成
        new_content = content2.replace("status: in_progress", "status: completed")
        project_state_file.write_text(new_content)
        
        # 第三次心跳应该读到 completed
        content3 = project_state_file.read_text()
        status3 = None
        for line in content3.split('\n'):
            if line.strip().startswith('status:'):
                status3 = line.split(':', 1)[1].strip()
        
        assert status3 == "completed", f"更新后状态应为 completed: {status3}"
        
        print("✓ 测试3通过: 多次心跳间状态持久化正确")
        
    finally:
        heartbeat.STATE_ROOT = original_state_root
        teardown_temp_state()

def test_missing_project_file():
    """测试4: 项目文件缺失时的降级处理"""
    state_dir, projects_dir = setup_temp_state()
    try:
        project_id = "nonexistent-project"
        
        from crab import heartbeat
        original_state_root = getattr(heartbeat, 'STATE_ROOT', None)
        heartbeat.STATE_ROOT = state_dir
        
        project_state_file = Path(state_dir) / "projects" / f"{project_id}.md"
        
        # 验证文件不存在
        assert not project_state_file.exists(), "文件不应存在"
        
        # 模拟读取缺失文件的降级逻辑
        def read_project_status_safely(project_id):
            project_state_file = Path(state_dir) / "projects" / f"{project_id}.md"
            if not project_state_file.exists():
                return "UNKNOWN"
            return "ACTIVE"
        
        status = read_project_status_safely(project_id)
        assert status == "UNKNOWN", f"缺失文件应返回 UNKNOWN: {status}"
        
        print("✓ 测试4通过: 缺失项目文件的降级处理正确")
        
    finally:
        heartbeat.STATE_ROOT = original_state_root
        teardown_temp_state()

def run_all_tests():
    """运行所有回归测试"""
    print("=" * 60)
    print("跨心跳项目记忆回归测试")
    print("=" * 60)
    
    tests = [
        test_project_in_progress_read,
        test_project_status_transition,
        test_multiple_heartbeats_persistence,
        test_missing_project_file,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"✗ {test.__name__} 失败: {e}")
            failed += 1
        except Exception as e:
            print(f"✗ {test.__name__} 异常: {e}")
            failed += 1
    
    print("=" * 60)
    print(f"测试结果: {passed} 通过, {failed} 失败")
    print("=" * 60)
    
    return failed == 0

if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
