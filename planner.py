"""
Planner module — 在每次心跳前决定：续推手上已有的项目，还是开新方向。
这是 opencrab 生命循环中「意图生成」决策层的入口。
"""
from pathlib import Path
import textwrap

PROJECTS_DIR = Path("state/projects")


def _read_project_briefs() -> list[str]:
    """读出所有跨心跳项目的摘要，供大脑在生成意图前参考。"""
    briefs = []

    # 【项目账·跨心跳路线图】
    zhang = Path("state/项目账.md")
    if zhang.exists():
        head = "\n".join(zhang.read_text("utf-8").splitlines()[:20]).strip()
        if head:
            briefs.append("【项目账·跨心跳路线图】\n" + head)

    # projects/*.md
    if not PROJECTS_DIR.exists():
        return briefs

    for md in sorted(PROJECTS_DIR.glob("*.md")):
        lines = [ln.strip() for ln in md.read_text("utf-8").splitlines() if ln.strip()]
        if not lines:
            continue
        title = lines[0].lstrip("# ").strip()[:80]
        hint = next((ln[:80] for ln in lines[1:]
                     if any(k in ln.lower() for k in
                            ("status", "状态", "in_progress", "进度",
                             "当前", "下一步", "next"))), "")
        briefs.append(
            f"- {md.name}：{title}" + ("  · " + hint if hint else "")
        )

    return briefs


def form_intent(topic: str, force_continue: bool = False) -> dict:
    """
    决定针对给定 topic 是「续旧」还是「开新」。
    返回 dict：
        strategy : "continue" | "start_new"
        project  : None | str(project_path)
        briefs   : list[str]  可直接塞进 prompt 的项目摘要
    """
    briefs = _read_project_briefs()

    if not briefs:
        return {"topic": topic, "strategy": "start_new",
                "project": None, "briefs": []}

    # 如果有未完成项目，且没有强制开新，则默认捞起最新的未完成项目
    if force_continue or _has_unfinished_projects():
        md = _get_latest_unfinished_project()
        if md:
            return {"topic": topic, "strategy": "continue",
                    "project": str(md), "briefs": briefs}

    # 简单匹配：topic 关键字出现在哪个项目文件里
    topic_lower = topic.lower()
    for md in sorted(PROJECTS_DIR.glob("*.md")):
        content = md.read_text("utf-8").lower()
        if topic_lower in content or topic_lower in md.stem.lower():
            return {"topic": topic, "strategy": "continue",
                    "project": str(md), "briefs": briefs}

    return {"topic": topic, "strategy": "start_new",
            "project": None, "briefs": briefs}


def _has_unfinished_projects() -> bool:
    """检查是否有未完成项目。"""
    if not PROJECTS_DIR.exists():
        return False
    for md in PROJECTS_DIR.glob("*.md"):
        content = md.read_text("utf-8")
        if "done" not in content.lower() and "完成" not in content:
            return True
    return False


def _get_latest_unfinished_project() -> Path | None:
    """获取最新的未完成项目。"""
    if not PROJECTS_DIR.exists():
        return None
    unfinished = []
    for md in sorted(PROJECTS_DIR.glob("*.md")):
        content = md.read_text("utf-8")
        if "done" not in content.lower() and "完成" not in content:
            unfinished.append(md)
    return unfinished[-1] if unfinished else None


def list_projects() -> list[str]:
    """返回所有跨心跳项目文件名（用于调试 / cap list）。"""
    if not PROJECTS_DIR.exists():
        return []
    return sorted(p.name for p in PROJECTS_DIR.glob("*.md"))


def project_prompt_block() -> str:
    """
    生成完整的「手上项目」提示块。
    直接塞进大脑 prompt，让它开拍前先决定「续旧还是开新」。
    """
    briefs = _read_project_briefs()
    if not briefs:
        return ""

    return (
        "📋 你手上正在推进的跨心跳项目（"
        "**开拍先决定：续推它、还是开新？**"
        "别又换个新鲜点子把它晾在半路——立过的山头没登顶就别下山）：\n"
        + "\n".join(briefs)
        + "\n"
    )
