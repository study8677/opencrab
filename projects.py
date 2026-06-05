# projects.py - Cross-heartbeat project memory (git-tracked, not in state/)
# All project progress lives here so "continue vs. new" decisions are in git.

import json
import os
from pathlib import Path
from datetime import datetime

_PROJECTS_DIR = Path("projects")


def ensure_projects_dir():
    _PROJECTS_DIR.mkdir(exist_ok=True)


def project_meta_path(project_id: str) -> Path:
    return _PROJECTS_DIR / f"{project_id}.json"


def create_project(
    project_id: str,
    name: str,
    description: str = "",
    fitness: str = "",
    tags: list[str] | None = None,
) -> dict:
    """Create a new project record in git-tracked projects/"""
    ensure_projects_dir()
    meta = {
        "project_id": project_id,
        "name": name,
        "description": description,
        "fitness": fitness,
        "tags": tags or [],
        "created_at": datetime.now().isoformat(),
        "last_heartbeat": datetime.now().isoformat(),
        "status": "active",
        "heartbeat_count": 0,
    }
    path = project_meta_path(project_id)
    path.write_text(json.dumps(meta, indent=2))
    return meta


def update_project(project_id: str, **kwargs) -> dict:
    """Update project fields"""
    path = project_meta_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Project {project_id} not found")
    meta = json.loads(path.read_text())
    meta.update(kwargs)
    meta["last_heartbeat"] = datetime.now().isoformat()
    path.write_text(json.dumps(meta, indent=2))
    return meta


def bump_heartbeat(project_id: str) -> dict:
    """Increment heartbeat counter for a project"""
    path = project_meta_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Project {project_id} not found")
    meta = json.loads(path.read_text())
    meta["heartbeat_count"] = meta.get("heartbeat_count", 0) + 1
    meta["last_heartbeat"] = datetime.now().isoformat()
    path.write_text(json.dumps(meta, indent=2))
    return meta


def get_project(project_id: str) -> dict:
    """Get project metadata"""
    path = project_meta_path(project_id)
    if not path.exists():
        raise FileNotFoundError(f"Project {project_id} not found")
    return json.loads(path.read_text())


def list_projects(status: str | None = None) -> list[dict]:
    """List all projects, optionally filtered by status"""
    ensure_projects_dir()
    projects = []
    for path in _PROJECTS_DIR.glob("*.json"):
        meta = json.loads(path.read_text())
        if status is None or meta.get("status") == status:
            projects.append(meta)
    return sorted(projects, key=lambda p: p.get("last_heartbeat", ""), reverse=True)


def get_active_project() -> dict | None:
    """Get the most recently heartbeat'd active project (continue vs. new decision)"""
    active = list_projects(status="active")
    return active[0] if active else None


def archive_project(project_id: str) -> dict:
    """Mark project as archived"""
    return update_project(project_id, status="archived")


def delete_project(project_id: str) -> None:
    """Remove project from git-tracked projects/"""
    path = project_meta_path(project_id)
    if path.exists():
        path.unlink()
        # Also remove notes/ dir if exists
        notes_dir = _PROJECTS_DIR / project_id
        if notes_dir.is_dir():
            import shutil
            shutil.rmtree(notes_dir)
