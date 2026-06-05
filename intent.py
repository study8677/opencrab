"""
Intent formation with project memory integration.
Ensures form_intent checks state/项目账.md and state/projects/*.md before starting new work.

Priority order:
  1. state/项目账.md (项目账——最高优先级，记录跨心跳承诺)
  2. state/projects/*.md (旧项目文件——兼容)

Before starting new work, always asks: "续做手上,还是开新?"
"""

import os
import glob
import yaml
from datetime import datetime
from pathlib import Path

PROJECTS_DIR = Path("state/projects")
ZHANG_PATH = Path("state/项目账.md")
DEFAULT_INTENT = {
    "intent": "Initialize crab evolution",
    "tier": "brainonly",
    "status": "draft"
}


def _load_zhang():
    """Load state/项目账.md as the primary project memory (highest priority)."""
    if not ZHANG_PATH.exists():
        return []

    try:
        content = ZHANG_PATH.read_text(encoding="utf-8")
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    data = yaml.safe_load(parts[2].strip())
                    if data and isinstance(data, dict):
                        data["_source"] = str(ZHANG_PATH)
                        data["_is_zhang"] = True
                        return [data]
                except yaml.YAMLError:
                    pass
        return []
    except Exception:
        return []


def _load_projects():
    """Load all project .md files from state/projects/*.md"""
    projects = []
    if not PROJECTS_DIR.exists():
        return projects
    
    for md_path in glob.glob(str(PROJECTS_DIR / "*.md")):
        try:
            content = Path(md_path).read_text(encoding="utf-8")
            # Parse frontmatter if present
            if content.startswith("---"):
                parts = content.split("---", 2)
                if len(parts) >= 3:
                    try:
                        data = yaml.safe_load(parts[2].strip())
                        if data:
                            data["_source"] = md_path
                            projects.append(data)
                    except yaml.YAMLError:
                        pass
            # Fallback: treat entire file as intent string
            projects.append({
                "intent": content.strip(),
                "_source": md_path,
                "status": "unknown"
            })
        except Exception:
            pass
    return projects


def _has_unfinished_projects(projects):
    """Check if any project is still in progress (not 'done', 'complete', 'archived')."""
    unfinished_keywords = ["in_progress", "active", "working", "draft", "ongoing", "pending"]
    done_keywords = ["done", "complete", "finished", "archived", "closed", "resolved"]
    
    for proj in projects:
        status = str(proj.get("status", "")).lower()
        # Skip if explicitly done
        if any(k in status for k in done_keywords):
            continue
        # Unfinished if has status in unfinished_keywords or no clear done status
        if not status or any(k in status for k in unfinished_keywords):
            return True
        # Also consider if it has an intent and no explicit completion
        if proj.get("intent") and not any(k in status for k in done_keywords):
            return True
    return False


def _update_project_progress(projects):
    """Write back updated progress to project files."""
    for proj in projects:
        source = proj.pop("_source", None)
        if not source:
            continue
        
        # Update timestamp and add progress note
        proj["last_considered"] = datetime.now().isoformat()
        if "progress_log" not in proj:
            proj["progress_log"] = []
        
        proj["progress_log"].append({
            "at": datetime.now().isoformat(),
            "action": "form_intent considered this project"
        })
        
        # Write back as YAML frontmatter in .md file
        try:
            md_path = Path(source)
            existing_content = md_path.read_text(encoding="utf-8")
            
            if existing_content.startswith("---"):
                parts = existing_content.split("---", 2)
                header = parts[1]
                body = parts[2].strip() if len(parts) > 2 else ""
            else:
                header = ""
                body = existing_content.strip()
            
            new_frontmatter = yaml.dump(proj, default_flow_style=False, allow_unicode=True)
            new_content = f"---\n{new_frontmatter}---\n\n{body}"
            md_path.write_text(new_content, encoding="utf-8")
        except Exception as e:
            print(f"Warning: failed to update {source}: {e}")


def form_intent(goal: str = None) -> dict:
    """
    Form intent by first checking for unfinished projects in state/projects/*.md.
    If unfinished projects exist, continue working on them instead of starting fresh.
    """
    projects = _load_projects()
    
    if _has_unfinished_projects(projects):
        # There are unfinished projects - continue deep work on them
        _update_project_progress(projects)
        
        # Return intent pointing to existing unfinished work
        first_unfinished = None
        for p in projects:
            if p.get("intent"):
                first_unfinished = p
                break
        
        if first_unfinished:
            return {
                "intent": f"Continue: {first_unfinished.get('intent', 'unfinished project')}",
                "tier": first_unfinished.get("tier", "brainonly"),
                "status": "continuing",
                "source": first_unfinished.get("_source", "unknown"),
                "from_projects": True
            }
        
        return {
            "intent": "Continue unfinished projects from state/projects/",
            "tier": "brainonly",
            "status": "continuing",
            "from_projects": True
        }
    
    # No unfinished projects - can start new work
    if goal:
        return {
            "intent": goal,
            "tier": "brainonly",
            "status": "new",
            "from_projects": False
        }
    
    return DEFAULT_INTENT.copy()


if __name__ == "__main__":
    # Test the function
    result = form_intent()
    print("Formed intent:", result)
    
    # Check what projects exist
    projects = _load_projects()
    print(f"Loaded {len(projects)} projects")
    for p in projects:
        print(f"  - {p.get('intent', 'unknown')}: {p.get('status', 'unknown')}")
    
    if _has_unfinished_projects(projects):
        print("There ARE unfinished projects - will continue existing work")
    else:
        print("No unfinished projects - may start new work")
