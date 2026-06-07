"""
Planner with project continuity gate.
Before each session, reads state/projects/项目账.md and forces explicit decision
on whether to continue, start fresh, or archive each incomplete project.
"""
import os
import re
from pathlib import Path
from typing import Optional


def _read_project_ledger(ledger_path: str) -> str:
    """Read the project ledger file. Returns empty string if not found."""
    try:
        with open(ledger_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def _parse_ledger_entries(ledger_content: str) -> list[dict]:
    """
    Parse entries from 续旧还是开新 ledger.
    Format expected:
        ## 项目名
        - 状态: [进行中|已暂停|待定]
        - 上次心跳: YYYY-MM-DD HH:MM
        - 备注: ...
    """
    entries = []
    if not ledger_content.strip():
        return entries

    # Split by ## headers (project names)
    parts = re.split(r"\n(?=##\s)", ledger_content)
    for part in parts:
        part = part.strip()
        if not part or not part.startswith("##"):
            continue

        lines = part.split("\n")
        name = lines[0].lstrip("#").strip()

        entry = {"name": name, "status": "进行中", "last_heartbeat": "", "note": ""}
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("- 状态:"):
                entry["status"] = line.replace("- 状态:", "").strip()
            elif line.startswith("- 上次心跳:"):
                entry["last_heartbeat"] = line.replace("- 上次心跳:", "").strip()
            elif line.startswith("- 备注:"):
                entry["note"] = line.replace("- 备注:", "").strip()

        entries.append(entry)
    return entries


def _render_ledger_review(entries: list[dict]) -> str:
    """Render ledger entries as a review prompt."""
    if not entries:
        return "没有未竟项目记录，可以开新。\n"

    lines = ["=== 未竟项目台 ===\n"]
    for i, e in enumerate(entries, 1):
        status_marker = "🔄" if e["status"] == "进行中" else "⏸"
        lines.append(
            f"{i}. {status_marker} {e['name']} [{e['status']}]"
        )
        if e["last_heartbeat"]:
            lines.append(f"   上次心跳: {e['last_heartbeat']}")
        if e["note"]:
            lines.append(f"   备注: {e['note']}")
        lines.append("   决策: [续推 / 开新 / 封存]\n")

    lines.append("请逐一做决定，输入 q 跳过剩余项目。")
    return "\n".join(lines)


def _update_ledger_entry(ledger_content: str, project_name: str, decision: str) -> str:
    """
    Update a ledger entry with the decision.
    decision: '续推' -> status becomes '进行中'
              '封存' -> status becomes '已封存'
              '开新' -> status stays same (handled by projects.py later)
    """
    if decision not in ("续推", "封存"):
        return ledger_content

    new_status = "进行中" if decision == "续推" else "已封存"

    # Find the project section
    pattern = rf"(##\s*{re.escape(project_name)}\b.*?)((?=\n##\s)|\Z)"
    match = re.search(pattern, ledger_content, re.DOTALL)

    if match:
        old_section = match.group(1)
        # Update status line
        if re.search(r"- 状态:", old_section):
            new_section = re.sub(r"- 状态:\s*[^\n]+", f"- 状态: {new_status}", old_section)
        else:
            # Insert status after project name
            new_section = re.sub(
                r"(##\s*{})".format(re.escape(project_name)),
                r"\1\n- 状态: {new_status}",
                old_section
            )

        # Add decision note
        import datetime
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
        decision_line = f"- 决策({timestamp}): {decision}"
        if re.search(r"- 决策\(", new_section):
            new_section = re.sub(r"- 决策\([^)]+\): [^\n]+", decision_line, new_section)
        else:
            new_section += f"\n{decision_line}"

        ledger_content = ledger_content.replace(old_section, new_section)

    return ledger_content


def _find_roadmap() -> Optional[str]:
    """Find the git-tracked ROADMAP.md. Searches upward from this file."""
    search_paths = [
        Path(__file__).parent / "ROADMAP.md",
        Path(__file__).parent.parent / "ROADMAP.md",
        Path(__file__).parent.parent.parent / "ROADMAP.md",
        "ROADMAP.md",
        "../ROADMAP.md",
    ]
    for p in search_paths:
        p = Path(p)
        if p.exists() and p.is_file():
            return str(p)
    return None


def read_roadmap() -> str:
    """
    Read the public roadmap. This is the FIRST thing read before each session.
    Returns the roadmap content, or a fallback message if not found.
    """
    roadmap_path = _find_roadmap()
    if roadmap_path and os.path.exists(roadmap_path):
        try:
            with open(roadmap_path, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            pass
    # Fallback: return empty but log
    return ""


def _summarize_roadmap(roadmap_content: str) -> str:
    """Extract a human-readable summary of active mountains from roadmap."""
    if not roadmap_content.strip():
        return "⚠️ ROADMAP.md 未找到或为空。"

    lines = ["=== 当前山头（每拍必看）===\n"]
    in_mountains = False
    for line in roadmap_content.split("\n"):
        if "## 当前山头" in line or "Active Mountains" in line.lower():
            in_mountains = True
            continue
        if in_mountains:
            if line.startswith("##"):
                break
            if line.strip():
                lines.append(line)
    if len(lines) == 1:
        lines.append("(暂无活跃山头)")
    return "\n".join(lines)


def gate_continuity(
    ledger_path: Optional[str] = None,
    dry_run: bool = False,
    auto_decision: Optional[str] = None,
    require_roadmap: bool = True,
) -> dict:
    """
    Gate that enforces project continuity review before each session.

    ⚡ 焊死闸门逻辑：
    - 必须读取 ROADMAP.md（强制）
    - 必须检查项目账（强制）
    - 有未竟项目时必须做出决策（强制）
    - 只有在没有未竟项目且 ROADMAP 可读时才能"放行"

    Args:
        ledger_path: Path to 续旧还是开新 ledger file.
                     Defaults to state/projects/项目账.md
        dry_run: If True, only show the review without blocking.
        auto_decision: 'continue_all' | 'archive_all' | None
                       If set, applies decision to all entries automatically.
        require_roadmap: If True, ROADMAP.md must be readable or it's a BLOCK.

    Returns:
        dict with keys:
            - decisions: {project_name: decision}
            - ledger_updated: bool (whether ledger was modified)
            - blocked: bool (True = gate did NOT pass, must handle before planning)
            - reason: str (why blocked, if any)
            - roadmap_content: str (the roadmap that was read)
    """
    # ============ 强制读取 ROADMAP ============
    roadmap_content = read_roadmap()
    roadmap_summary = _summarize_roadmap(roadmap_content)

    if require_roadmap and not roadmap_content.strip():
        return {
            "decisions": {},
            "ledger_updated": False,
            "blocked": True,
            "reason": "ROADMAP.md_missing_or_empty",
            "roadmap_content": "",
            "roadmap_summary": roadmap_summary,
            "message": "🚫 闸门未通过：ROADMAP.md 未找到或为空。请先创建 ROADMAP.md 并至少填入当前山头。",
        }

    # ============ 找项目账 ============
    if ledger_path is None:
        # Try default location
        default_paths = [
            "state/projects/项目账.md",
            "../state/projects/项目账.md",
            Path(__file__).parent.parent / "state/projects/项目账.md",
        ]
        for p in default_paths:
            if os.path.exists(p):
                ledger_path = p
                break

    # ============ 分析项目账 ============
    if ledger_path and os.path.exists(ledger_path):
        ledger_content = _read_project_ledger(ledger_path)
        entries = _parse_ledger_entries(ledger_content)
        incomplete = [e for e in entries if e["status"] in ("进行中", "待定")]
    else:
        ledger_content = ""
        incomplete = []

    # ============ 无未竟项目 → 放行（但先展示山头摘要） ============
    if not incomplete:
        return {
            "decisions": {},
            "ledger_updated": False,
            "blocked": False,
            "reason": "no_incomplete_projects",
            "roadmap_content": roadmap_content,
            "roadmap_summary": roadmap_summary,
            "message": f"✅ 闸门通过：无未竟项目。\n\n{roadmap_summary}",
        }

    # ============ 有未竟项目 → 必须决策（焊死的闸） ============
    decisions = {}

    if dry_run:
        print(_render_ledger_review(incomplete))
        return {
            "decisions": {},
            "ledger_updated": False,
            "blocked": False,  # preview only
            "preview": True,
            "roadmap_content": roadmap_content,
            "roadmap_summary": roadmap_summary,
        }

    if auto_decision == "continue_all":
        decisions = {e["name"]: "续推" for e in incomplete}
    elif auto_decision == "archive_all":
        decisions = {e["name"]: "封存" for e in incomplete}
    else:
        # Interactive mode - THIS IS THE WELDED GATE
        # In interactive mode we return and let external UI handle the prompt
        # But we mark blocked=True until a decision is made
        return {
            "decisions": {},
            "ledger_updated": False,
            "blocked": True,
            "reason": "decision_required",
            "review_prompt": _render_ledger_review(incomplete),
            "entries": incomplete,
            "roadmap_content": roadmap_content,
            "roadmap_summary": roadmap_summary,
            "message": (
                f"🚫 闸门未通过：有 {len(incomplete)} 个未竟项目。\n"
                f"必须做出决定后才能继续规划。\n\n"
                f"当前山头：\n{roadmap_summary}\n\n"
                f"未竟项目：\n{_render_ledger_review(incomplete)}"
            ),
        }

    # ============ 应用决策到项目账 ============
    updated_content = ledger_content
    for name, decision in decisions.items():
        updated_content = _update_ledger_entry(updated_content, name, decision)

    if updated_content != ledger_content and ledger_path:
        with open(ledger_path, "w", encoding="utf-8") as f:
            f.write(updated_content)

    return {
        "decisions": decisions,
        "ledger_updated": updated_content != ledger_content,
        "blocked": False,
        "roadmap_content": roadmap_content,
        "roadmap_summary": roadmap_summary,
        "message": f"✅ 闸门通过。决策已应用。\n\n当前山头：\n{roadmap_summary}",
    }


def plan_with_continuity_gate(
    task: str,
    ledger_path: Optional[str] = None,
    require_roadmap: bool = True,
    **kwargs,
) -> dict:
    """
    Main entry point: enforce continuity gate, then proceed with planning.

    ⚡ 这是焊死的闸门：
    1. 必须先读取 ROADMAP.md（显示当前山头）
    2. 必须检查项目账
    3. 有未竟项目时必须做出续旧/封存决策
    4. 只有闸门完全通过才能调用 crab.plan()

    这个函数是 self-mod 的核心锚点——确保每次规划都被山头牵着深耕，
    不再被惯性推着换新点子。

    Args:
        task: The planning task.
        ledger_path: Path to project ledger. Defaults to state/projects/项目账.md.
        require_roadmap: If True, ROADMAP.md must be readable or planning is blocked.
        **kwargs: Additional args passed to gate_continuity and crab.plan.

    Returns:
        dict with planning result, or blocked status if gate not passed.
    """
    # Pass require_roadmap to the gate
    gate_result = gate_continuity(
        ledger_path=ledger_path,
        require_roadmap=require_roadmap,
        **kwargs,
    )

    # ============ 闸门检查 ============
    if gate_result.get("blocked"):
        # Gate NOT passed - cannot proceed with planning
        return {
            "blocked": True,
            "reason": gate_result.get("reason", "unknown"),
            "gate_result": gate_result,
            "message": gate_result.get("message", "闸门未通过"),
            "roadmap_summary": gate_result.get("roadmap_summary", ""),
        }

    # ============ 闸门通过 → 执行规划 ============
    # Import here to avoid circular
    try:
        from crab import plan
        plan_result = plan(task, **kwargs)
        # Attach gate info to the result
        plan_result["_gate"] = {
            "passed": True,
            "roadmap_summary": gate_result.get("roadmap_summary", ""),
            "decisions": gate_result.get("decisions", {}),
            "ledger_updated": gate_result.get("ledger_updated", False),
        }
        return plan_result
    except ImportError:
        # Fallback: return gate result with note
        return {
            "blocked": False,
            "gate_result": gate_result,
            "task": task,
            "note": "crab.plan not available, continuity gate passed but planning skipped",
        }


def form_intent(task: str, ledger_path: Optional[str] = None, **kwargs) -> dict:
    """
    ⚡ 焊死的入口：form_intent 必须先读 state/projects/ 再决定规划方向。

    这是项目路线图的根锚点——每次醒来不再当金鱼忘掉上次在做什么。
    流程：
    1. 读取 ROADMAP.md（当前山头）
    2. 检查 state/projects/ 项目账
    3. 问「续旧还是开新」（blocked=True 等待决策）
    4. 闸门通过后才调用 crab.plan()

    Args:
        task: The intent/task to plan for.
        ledger_path: Path to project ledger. Defaults to state/projects/项目账.md.
        **kwargs: Additional args passed to gate_continuity and crab.plan.

    Returns:
        dict with:
            - blocked: bool (True=需决策，False=闸门通过可规划)
            - reason: str (why blocked, if any)
            - review_prompt: str (interactive prompt for decisions)
            - entries: list[dict] (incomplete projects)
            - roadmap_summary: str
            - 如果 blocked=False，还有 plan_result
    """
    return plan_with_continuity_gate(
        task=task,
        ledger_path=ledger_path,
        require_roadmap=True,
        **kwargs,
    )


if __name__ == "__main__":
    import sys

    def print_result(label: str, result: dict):
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
        blocked = result.get("blocked", False)
        status = "🚫 阻塞" if blocked else "✅ 通过"
        print(f"状态: {status}")
        if result.get("reason"):
            print(f"原因: {result['reason']}")
        if result.get("message"):
            print(f"\n{result['message']}")
        if result.get("decisions"):
            print(f"\n决策: {result['decisions']}")
        if result.get("roadmap_summary"):
            print(f"\n{result['roadmap_summary']}")
        print()

    if len(sys.argv) > 1:
        if sys.argv[1] == "--review":
            result = gate_continuity(dry_run=True)
            print_result("DRY RUN 预览", result)
        elif sys.argv[1] == "--continue-all":
            result = gate_continuity(auto_decision="continue_all")
            print_result("AUTO: 续推所有", result)
        elif sys.argv[1] == "--archive-all":
            result = gate_continuity(auto_decision="archive_all")
            print_result("AUTO: 封存所有", result)
        elif sys.argv[1] == "--roadmap":
            content = read_roadmap()
            print(f"\n{'='*60}")
            print("  ROADMAP.md 内容")
            print(f"{'='*60}")
            if content:
                print(content)
            else:
                print("⚠️ ROADMAP.md 未找到")
        elif sys.argv[1] == "--plan":
            # Full flow: gate → plan
            if len(sys.argv) < 3:
                print("用法: python planner.py --plan '<task>'")
                sys.exit(1)
            task = " ".join(sys.argv[2:])
            result = plan_with_continuity_gate(task)
            if result.get("blocked"):
                print_result("⚠️ 规划被闸门阻塞", result)
            else:
                print_result("✅ 规划成功", result)
                if result.get("note"):
                    print(f"注: {result['note']}")
        else:
            result = gate_continuity()
            print_result("闸门检查", result)
    else:
        result = gate_continuity()
        print_result("闸门检查", result)
