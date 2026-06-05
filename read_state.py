"""Utility to read/write the active project state."""
import json
from pathlib import Path

STATE_DIR = Path(__file__).parent / "state" / "projects"
STATE_FILE = STATE_DIR / "active.json"

def load_active() -> dict:
    """Load active project state. Returns empty dict if none."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {}

def save_active(state: dict) -> None:
    """Write active project state."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"[state] wrote {STATE_FILE}")

def ask_continue_or_new() -> str:
    """Prompt user: continue previous project or start new?"""
    current = load_active()
    if current:
        print(f"[state] Active project: {current.get('name', '?')} "
              f"(拍 {current.get('beat', 0)})")
    while True:
        choice = input("[state] 续旧 [o] / 开新 [n]? ").strip().lower()
        if choice in ("o", "n"):
            return choice
        print("  输 o 或 n")

def start_new_project() -> dict:
    """Start a fresh project state."""
    name = input("[state] 项目名: ").strip() or "scratch"
    state = {
        "name": name,
        "beat": 0,
        "last_action": None,
        "history": []
    }
    save_active(state)
    return state

def resume_project() -> dict:
    """Load existing project state."""
    return load_active()

def bump_beat(state: dict, action: str) -> dict:
    """Increment beat, record action, save."""
    state["beat"] = state.get("beat", 0) + 1
    state["last_action"] = action
    state.setdefault("history", []).append({
        "beat": state["beat"],
        "action": action
    })
    save_active(state)
    return state
