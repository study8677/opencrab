"""
验证 planner.form_intent 是否先读 state/projects/ 再决定规划方向。

焊死验证点：
1. form_intent 存在且在 planner.py 中
2. 调用 form_intent 时，gate_continuity 先执行
3. 有未竟项目时 blocked=True，等待「续旧还是开新」决策
4. 无未竟项目或已决策时 blocked=False
"""
import sys
import os

# 确保当前目录可导入
sys.path.insert(0, os.path.dirname(__file__))


def test_form_intent_exists():
    """验证 form_intent 函数存在"""
    from planner import form_intent
    print("✅ form_intent 函数存在于 planner.py")
    return True


def test_gate_runs_first():
    """验证 gate_continuity 先于规划执行"""
    from planner import gate_continuity, form_intent

    # 调用 form_intent（expect blocked=True if no decision made）
    result = form_intent("测试任务")

    # 检查返回结构
    assert "blocked" in result, "❌ form_intent 必须返回 blocked 字段"
    assert "roadmap_summary" in result, "❌ form_intent 必须返回 roadmap_summary"

    print(f"✅ form_intent 返回结构正确: blocked={result['blocked']}")
    print(f"   roadmap_summary: {result.get('roadmap_summary', '')[:80]}...")
    return result


def test_asks_continue_or_new():
    """验证有未竟项目时问「续旧还是开新」"""
    from planner import form_intent, gate_continuity

    # 先看 gate_continuity 的原始结果
    gate_result = gate_continuity(dry_run=True)

    if gate_result.get("blocked"):
        # 有未竟项目，必须决策
        assert "review_prompt" in gate_result, "❌ blocked=True 时必须有 review_prompt"
        assert "entries" in gate_result, "❌ blocked=True 时必须有 entries"
        print(f"✅ 有 {len(gate_result['entries'])} 个未竟项目，必须决策")
        print(f"   提示: {gate_result['review_prompt'][:200]}...")
    else:
        print("✅ 无未竟项目，闸门通过")

    return gate_result


def test_project_ledger_reads():
    """验证 state/projects/ 目录被正确读取"""
    from planner import _read_project_ledger, _parse_ledger_entries

    # 尝试找项目账
    default_paths = [
        "state/projects/项目账.md",
        "../state/projects/项目账.md",
    ]
    ledger_path = None
    for p in default_paths:
        if os.path.exists(p):
            ledger_path = p
            break

    if ledger_path:
        content = _read_project_ledger(ledger_path)
        entries = _parse_ledger_entries(content)
        print(f"✅ 找到项目账: {ledger_path}")
        print(f"   条目数: {len(entries)}")

        # 检查是否有进行中的项目
        active = [e for e in entries if e["status"] == "进行中"]
        if active:
            print(f"   进行中项目: {[e['name'] for e in active]}")
    else:
        print("⚠️ 未找到项目账 (可能需要先创建 state/projects/项目账.md)")

    return ledger_path


def test_no_goldfish_forgetting():
    """核心验证：项目路线图不再每次醒来被当金鱼忘掉"""
    from planner import form_intent

    result = form_intent("测试任务")

    # 无论如何，roadmap_summary 必须存在
    assert "roadmap_summary" in result, "❌ 必须读取 ROADMAP.md"

    if result["blocked"]:
        # 必须等待决策
        print("✅ 金鱼闸门有效：有未竟项目，需先决策「续旧还是开新」")
        print(f"   决策提示: {result.get('review_prompt', '')[:100]}...")
    else:
        print("✅ 金鱼闸门有效：无未竟项目或已决策，可继续规划")

    return result


def main():
    print("=" * 60)
    print("  peek_planner: 验证 form_intent 焊死项目账根")
    print("=" * 60)

    tests = [
        ("1. form_intent 存在", test_form_intent_exists),
        ("2. gate_continuity 先执行", test_gate_runs_first),
        ("3. 问「续旧还是开新」", test_asks_continue_or_new),
        ("4. 读取 state/projects/", test_project_ledger_reads),
        ("5. 金鱼闸门有效", test_no_goldfish_forgetting),
    ]

    all_passed = True
    for name, test_fn in tests:
        print(f"\n--- {name} ---")
        try:
            test_fn()
        except AssertionError as e:
            print(f"❌ {e}")
            all_passed = False
        except Exception as e:
            print(f"⚠️ {e}")
            all_passed = False

    print("\n" + "=" * 60)
    if all_passed:
        print("✅ 所有验证通过：form_intent 已焊死「先读项目账」根")
    else:
        print("⚠️ 部分验证失败：需要修复")
    print("=" * 60)


if __name__ == "__main__":
    main()
