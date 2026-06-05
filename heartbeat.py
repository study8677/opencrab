"""
心跳驱动：每次迭代检查项目状态，决定继续/封存/开新。
"""

import time
from pathlib import Path
from crab import memory, intent, ledger, cadence, health

# 默认 state 根目录（可被测试覆写）
STATE_ROOT = Path(__file__).parent.parent / "state"

PROJECTS_DIR = STATE_ROOT / "projects"


def read_project_status(project_id: str) -> str:
    """
    读取 state/projects/<id>.md，返回 status 字段。
    缺失文件返回 "UNKNOWN"。
    """
    path = PROJECTS_DIR / f"{project_id}.md"
    if not path.exists():
        return "UNKNOWN"
    for line in path.read_text().splitlines():
        stripped = line.strip()
        if stripped.startswith("status:"):
            return stripped.split(":", 1)[1].strip()
    return "UNKNOWN"


def get_active_project_id() -> str | None:
    """
    扫描 projects 目录，返回第一个 in_progress 项目的 id。
    无 in_progress 项目返回 None。
    """
    if not PROJECTS_DIR.exists():
        return None
    for md_path in sorted(PROJECTS_DIR.glob("*.md")):
        # id 就是文件名（不含 .md）
        pid = md_path.stem
        if read_project_status(pid) == "in_progress":
            return pid
    return None


def heartbeat_form_intent_decision(project_id: str | None) -> str:
    """
    心跳时 form_intent 调度逻辑：
    - 有 in_progress 项目 → 继续该项目
    - 项目已 completed/archived → 封存，尝试开新
    - 无 in_progress 项目 → 开新
    - 项目状态 UNKNOWN → 开新
    """
    if project_id is None:
        return "NEW"

    status = read_project_status(project_id)
    if status == "in_progress":
        return "CONTINUE"
    elif status in ("completed", "archived", "paused"):
        return "ARCHIVE_THEN_NEW"
    else:  # UNKNOWN or other
        return "NEW"


def run_heartbeat_once() -> dict:
    """
    一次心跳：查项目状态 → form_intent 决策 → 记录 cadence。
    """
    project_id = get_active_project_id()
    decision = heartbeat_form_intent_decision(project_id)

    result = {
        "timestamp": time.time(),
        "active_project": project_id,
        "status": read_project_status(project_id) if project_id else None,
        "decision": decision,
    }

    cadence.record_pulse(
        project_id=project_id,
        decision=decision,
        status=result["status"],
    )

    return result
