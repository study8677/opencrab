#!/usr/bin/env python3
"""
心跳焊接验证实验：
1. 写一个未完成项目到 state/projects/
2. 跑 form_intent 验证是否返回 continue
3. 如果失败，brain-only 修 planner.py 并 commit
"""
import sys
sys.path.insert(0, ".")

from pathlib import Path
import subprocess

def run_heartbeat_weld_verify():
    print("=" * 70)
    print("心跳焊接验证实验")
    print("=" * 70)
    
    # Step 1: 确认未完成项目存在
    test_project = Path("state/projects/test_incomplete_heartbeat_weld.md")
    if not test_project.exists():
        print(f"❌ 未完成项目不存在: {test_project}")
        print("请先运行本目录下的脚本创建项目...")
        return False
        
    print(f"\n📋 未完成项目: {test_project}")
    content = test_project.read_text("utf-8")
    print("内容预览:")
    for i, line in enumerate(content.splitlines()[:15], 1):
        print(f"  {i:2d}: {line}")
    
    # Step 2: 验证 form_intent
    print("\n" + "-" * 70)
    print("Step 2: 验证 form_intent 是否续推")
    print("-" * 70)
    
    result = subprocess.run(
        [sys.executable, "verify_form_intent_continue.py"],
        capture_output=True, text=True
    )
    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)
    
    if result.returncode != 0:
        print("\n⚠️  form_intent 没有正确续推未完成项目！")
        print("需要 brain-only 修复 planner.py")
        
        # Step 3: 读取当前 planner.py 并分析
        planner_path = Path("planner.py")
        planner_content = planner_path.read_text("utf-8")
        
        # 分析问题：form_intent 的匹配逻辑可能太严格
        # 当前逻辑：topic_lower in content or topic_lower in md.stem.lower()
        # 问题：topic "heartbeat weld test" 可能没完全匹配
        
        print("\n分析 form_intent 逻辑...")
        
        # 简单修复：扩大匹配范围，包含 briefs 中的项目
        # 当前 briefs 包含项目内容，我们可以让它也参与匹配
        
        # 找到 form_intent 函数的返回 "continue" 部分
        # 并增强匹配逻辑
        
        # 这里先报告情况，由人工决定是否改
        print("\n可能的修复方案：")
        print("1. 扩大 topic 匹配范围（包含更多关键词）")
        print("2. 让 form_intent 检查 briefs 列表中的项目")
        print("3. 改用模糊匹配而非精确包含")
        
        return False
    else:
        print("\n✅ form_intent 验证通过！")
        print("心跳应该能正确续推未完成项目")
        return True

if __name__ == "__main__":
    ok = run_heartbeat_weld_verify()
    sys.exit(0 if ok else 1)
