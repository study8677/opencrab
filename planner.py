"""
Planner module — reads state/projects/*.md to decide: continue existing or start new.
"""
import os
import glob
from pathlib import Path

PROJECTS_DIR = Path("state/projects")

def form_intent(topic: str) -> dict:
    """
    Read all state/projects/*.md, return intent dict.
    If a project matches the topic, return 'continue' intent.
    Otherwise, return 'start_new' intent.
    """
    intent = {"topic": topic, "strategy": "start_new", "project": None}

    if not PROJECTS_DIR.exists():
        return intent

    for md_path in sorted(PROJECTS_DIR.glob("*.md")):
        content = md_path.read_text()
        # Check if this project matches the topic
        if topic.lower() in content.lower() or topic.lower() in md_path.stem.lower():
            return {"topic": topic, "strategy": "continue", "project": str(md_path)}

    return intent


def list_projects():
    """Return list of existing project .md files."""
    if not PROJECTS_DIR.exists():
        return []
    return sorted(P.name for p in PROJECTS_DIR.glob("*.md"))
