#!/usr/bin/env python3
"""
Heartbeat mechanism - tracks ongoing tasks, reports fitness, coordinates the system.
This is the core lifeline of the crab organism.
"""
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Any

STATE_DIR = Path("state")
TASKS_FILE = STATE_DIR / "heartbeat_tasks.json"
FITNESS_FILE = STATE_DIR / "fitness.json"
PROJECTS_FILE = STATE_DIR / "projects_ledger.json"

def ensure_state():
    """Ensure state directory and files exist."""
    STATE_DIR.mkdir(exist_ok=True)
    for f in [TASKS_FILE, FITNESS_FILE, PROJECTS_FILE]:
        if not f.exists():
            f.write_text("[]" if f != FITNESS_FILE else "{}")

def load_tasks() -> list[dict]:
    ensure_state()
    with open(TASKS_FILE) as f:
        return json.load(f)

def save_tasks(tasks: list[dict]):
    ensure_state()
    with open(TASKS_FILE, 'w') as f:
        json.dump(tasks, f, indent=2)

def load_fitness() -> dict:
    ensure_state()
    if FITNESS_FILE.exists():
        with open(FITNESS_FILE) as f:
            return json.load(f)
    return {}

def save_fitness(data: dict):
    ensure_state()
    with open(FITNESS_FILE, 'w') as f:
        json.dump(data, f, indent=2)

def pulse(task_name: str, status: str = "IN_PROGRESS", metadata: dict = None) -> bool:
    """Record a heartbeat pulse for a task."""
    tasks = load_tasks()
    
    # Find or create task
    found = False
    for t in tasks:
        if t.get("name") == task_name:
            t["status"] = status
            t["last_pulse"] = datetime.now().isoformat()
            if metadata:
                t.update(metadata)
            found = True
            break
    
    if not found:
        tasks.append({
            "name": task_name,
            "status": status,
            "created": datetime.now().isoformat(),
            "last_pulse": datetime.now().isoformat(),
            **(metadata or {})
        })
    
    save_tasks(tasks)
    return True

def get_task_status(task_name: str) -> str:
    """Get the current status of a task."""
    tasks = load_tasks()
    for t in tasks:
        if t.get("name") == task_name:
            return t.get("status", "unknown")
    return "not_found"

def complete_task(task_name: str, fitness_score: float = 1.0):
    """Mark a task as complete and record its fitness."""
    # Update tasks
    tasks = load_tasks()
    for t in tasks:
        if t.get("name") == task_name:
            t["status"] = "DONE"
            t["completed"] = datetime.now().isoformat()
            break
    save_tasks(tasks)
    
    # Update fitness
    fitness = load_fitness()
    fitness[task_name] = fitness_score
    save_fitness(fitness)

def get_all_statuses() -> dict:
    """Get all task statuses."""
    tasks = load_tasks()
    return {t.get("name"): t.get("status") for t in tasks}

def get_fitness(task_name: str = None) -> Any:
    """Get fitness score(s)."""
    fitness = load_fitness()
    if task_name:
        return fitness.get(task_name)
    return fitness

# === CLI Interface ===
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: heartbeat.py <command> [args]")
        print("Commands: pulse, status, complete, fitness, list")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "pulse":
        name = sys.argv[2] if len(sys.argv) > 2 else "default"
        pulse(name)
        print(f"Pulsed: {name}")
    
    elif cmd == "status":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        if name:
            print(f"{name}: {get_task_status(name)}")
        else:
            for n, s in get_all_statuses().items():
                print(f"  {n}: {s}")
    
    elif cmd == "complete":
        name = sys.argv[2] if len(sys.argv) > 2 else "default"
        score = float(sys.argv[3]) if len(sys.argv) > 3 else 1.0
        complete_task(name, score)
        print(f"Completed: {name} = {score}")
    
    elif cmd == "fitness":
        name = sys.argv[2] if len(sys.argv) > 2 else None
        print(get_fitness(name))
    
    elif cmd == "list":
        for n, s in get_all_statuses().items():
            print(f"  [{s}] {n}")
    
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
