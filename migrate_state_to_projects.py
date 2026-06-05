#!/usr/bin/env python3
# migrate_state_to_projects.py
# One-shot migration: move project-related data from state/ to git-tracked projects/
# Run once, then this file can be deleted.

import json
import shutil
from pathlib import Path

STATE_DIR = Path("state")
PROJECTS_DIR = Path("projects")


def migrate():
    PROJECTS_DIR.mkdir(exist_ok=True)

    # Migrate project-state.json if exists
    src = STATE_DIR / "project-state.json"
    if src.exists():
        data = json.loads(src.read_text())
        for project_id, meta in data.items():
            dst = PROJECTS_DIR / f"{project_id}.json"
            if not dst.exists():
                dst.write_text(json.dumps(meta, indent=2))
                print(f"  Migrated: {project_id}")
        print(f"Migrated {len(data)} projects from state/project-state.json")

    # Migrate state/fitness/ -> projects/ (per-project fitness notes)
    fitness_src = STATE_DIR / "fitness"
    if fitness_src.is_dir():
        for subdir in fitness_src.iterdir():
            if subdir.is_dir():
                project_id = subdir.name
                notes_dst = PROJECTS_DIR / project_id
                notes_dst.mkdir(exist_ok=True)
                for f in subdir.glob("*.md"):
                    shutil.copy2(f, notes_dst / f.name)
                print(f"  Migrated fitness notes for: {project_id}")

    # Migrate state/*.json project files
    if STATE_DIR.is_dir():
        for f in STATE_DIR.glob("*.json"):
            # Skip non-project state files
            if f.name in ("project-state.json", "heartbeat.json", "memory.json"):
                continue
            # Treat as project if it has project_id or name field
            try:
                data = json.loads(f.read_text())
                if "project_id" in data or "name" in data:
                    project_id = data.get("project_id", data.get("name", f.stem))
                    dst = PROJECTS_DIR / f"{project_id}.json"
                    if not dst.exists():
                        dst.write_text(json.dumps(data, indent=2))
                        print(f"  Migrated: {f.name} -> {project_id}")
            except Exception:
                pass

    print("\nMigration complete. Verify with: ls projects/")
    print("Then update .gitignore and commit.")


if __name__ == "__main__":
    migrate()
