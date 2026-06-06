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


def gate_continuity(
    ledger_path: Optional[str] = None,
    dry_run: bool = False,
    auto_decision: Optional[str] = None,
) -> dict:
    """
    Gate that enforces project continuity review before each session.

    Args:
        ledger_path: Path to 续旧还是开新 ledger file.
                     Defaults to state/projects/项目账.md
        dry_run: If True, only show the review without blocking.
        auto_decision: 'continue_all' | 'archive_all' | None
                       If set, applies decision to all entries automatically.

    Returns:
        dict with keys:
            - decisions: {project_name: decision}
            - ledger_updated: bool (whether ledger was modified)
            - skipped: bool (user chose to skip)
    """
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
        else:
            return {
                "decisions": {},
                "ledger_updated": False,
                "skipped": True,
                "reason": "no_ledger_found",
            }

    if not os.path.exists(ledger_path):
        return {
            "decisions": {},
            "ledger_updated": False,
            "skipped": True,
            "reason": "ledger_not_found",
        }

    ledger_content = _read_project_ledger(ledger_path)
    entries = _parse_ledger_entries(ledger_content)
    incomplete = [e for e in entries if e["status"] in ("进行中", "待定")]

    if not incomplete:
        return {
            "decisions": {},
            "ledger_updated": False,
            "skipped": False,
            "reason": "no_incomplete_projects",
        }

    decisions = {}

    if dry_run:
        print(_render_ledger_review(incomplete))
        return {"decisions": {}, "ledger_updated": False, "skipped": False, "preview": True}

    if auto_decision == "continue_all":
        decisions = {e["name"]: "续推" for e in incomplete}
    elif auto_decision == "archive_all":
        decisions = {e["name"]: "封存" for e in incomplete}
    else:
        # Interactive mode - in practice, this would be handled by CLI/HUD
        # Here we return the review prompt for external consumption
        print(_render_ledger_review(incomplete))
        return {
            "decisions": {},
            "ledger_updated": False,
            "skipped": False,
            "review_prompt": _render_ledger_review(incomplete),
            "entries": incomplete,
        }

    # Apply decisions to ledger
    updated_content = ledger_content
    for name, decision in decisions.items():
        updated_content = _update_ledger_entry(updated_content, name, decision)

    if updated_content != ledger_content:
        with open(ledger_path, "w", encoding="utf-8") as f:
            f.write(updated_content)
        return {
            "decisions": decisions,
            "ledger_updated": True,
            "skipped": False,
        }

    return {"decisions": decisions, "ledger_updated": False, "skipped": False}


def plan_with_continuity_gate(
    task: str,
    ledger_path: Optional[str] = None,
    **kwargs,
) -> dict:
    """
    Main entry point: enforce continuity gate, then proceed with planning.

    This is the "weld" - before planning, the gate must be passed.
    """
    gate_result = gate_continuity(ledger_path=ledger_path, **kwargs)

    # If gate blocked (no decision made), return early
    if gate_result.get("skipped") and not gate_result.get("decisions"):
        if gate_result.get("reason") in ("no_incomplete_projects", "no_ledger_found"):
            # Clear to proceed
            pass
        else:
            return {
                "blocked": True,
                "reason": gate_result.get("reason", "unknown"),
                "gate_result": gate_result,
            }

    # Import here to avoid circular
    try:
        from crab import plan
        return plan(task, **kwargs)
    except ImportError:
        # Fallback: just return the gate result
        return {
            "blocked": False,
            "gate_result": gate_result,
            "task": task,
            "note": "crab.plan not available, continuity gate passed",
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        if sys.argv[1] == "--review":
            result = gate_continuity(dry_run=True)
            print(result)
        elif sys.argv[1] == "--continue-all":
            result = gate_continuity(auto_decision="continue_all")
            print(f"Decisions: {result}")
        elif sys.argv[1] == "--archive-all":
            result = gate_continuity(auto_decision="archive_all")
            print(f"Decisions: {result}")
        else:
            result = gate_continuity()
            print(result)
    else:
        result = gate_continuity()
        print(result)
