#!/usr/bin/env python3
"""验证 form_intent 是否正确识别未完成项目并返回 continue 策略。"""
import sys
sys.path.insert(0, ".")

from planner import form_intent, list_projects, PROJECTS_DIR
from pathlib import Path

def main():
    print("=" * 60)
    print("验证 form_intent 是否续推未完成项目")
    print("=" * 60)

    # 1. 列出所有项目
    projects = list_projects()
    print(f"\n当前项目数: {len(projects)}")
    for p in projects:
        print(f"  - {p}")

    # 2. 验证测试项目是否存在
    test_project = PROJECTS_DIR / "test_incomplete_heartbeat_weld.md"
    assert test_project.exists(), f"测试项目不存在: {test_project}"
    print(f"\n✓ 测试项目存在: {test_project}")

    # 3. 调用 form_intent，topic 匹配测试项目
    topic = "heartbeat weld test"
    result = form_intent(topic)

    print(f"\nform_intent(topic='{topic}') 返回:")
    print(f"  strategy: {result['strategy']}")
    print(f"  project:  {result['project']}")
    print(f"  briefs 数量: {len(result['briefs'])}")

    # 4. 断言验证
    if result['strategy'] == 'continue' and result['project']:
        print(f"\n✅ 验证通过: form_intent 正确识别并选择续推")
        # 确认 project 指向测试项目
        if 'test_incomplete_heartbeat_weld' in result['project']:
            print(f"✅ 项目指向正确: {result['project']}")
        else:
            print(f"⚠️ 项目指向可能不对: {result['project']}")
        return True
    else:
        print(f"\n❌ 验证失败: strategy={result['strategy']}, project={result['project']}")
        print("   说明 form_intent 没有正确识别未完成项目")
        return False

if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
