#!/usr/bin/env python3
"""Quick delta view: compare current fitness.json with previous snapshot."""
import json
import sys
from pathlib import Path

def load_fitness(path):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception as e:
            print(f"[fitness_delta] could not load {path}: {e}")
    return None

def main():
    state_dir = Path("state")
    fitness_path = state_dir / "fitness.json"
    history_path = state_dir / "fitness_history.json"

    current = load_fitness(fitness_path)
    history = load_fitness(history_path) or []

    if not current:
        print("[fitness_delta] no current fitness data — run crab heartbeat first")
        sys.exit(1)

    # show current snapshot
    print("=== CURRENT FITNESS ===")
    ts = current.get("timestamp", "?")
    hb = current.get("heartbeat", "?")
    print(f"  timestamp: {ts}  heartbeat: #{hb}")
    comp = current.get("composite", 0)
    print(f"  composite score: {comp:.2f} ({int(comp*4)}/4 passed)")

    for metric in ["arena", "boundaryeval", "regression", "canary"]:
        m = current.get(metric, {})
        status = "●" if m.get("success") else "○"
        summary = m.get("summary", "")[:80]
        print(f"  {status} {metric}: {summary}")

    # delta vs previous in history
    if history:
        prev = history[-1]
        print("\n=== DELTA vs PREVIOUS ===")
        p_comp = prev.get("composite", 0)
        delta = comp - p_comp
        arrow = "↑" if delta > 0 else "↓" if delta < 0 else "→"
        print(f"  composite: {p_comp:.2f} {arrow} {comp:.2f} (Δ={delta:+.2f})")

        for metric in ["arena", "boundaryeval", "regression", "canary"]:
            p_ok = prev.get(metric, {}).get("success")
            c_ok = current.get(metric, {}).get("success")
            if p_ok is None and c_ok is None:
                continue
            icon = "●"
            delta_str = "unchanged"
            if c_ok and not p_ok:
                icon = "○→●"
                delta_str = "IMPROVED"
            elif not c_ok and p_ok:
                icon = "●→○"
                delta_str = "REGRESSED"
            elif p_ok == c_ok:
                delta_str = "unchanged"
            print(f"  {metric}: {icon} {delta_str}")

    # append to history
    history.append({"timestamp": ts, "heartbeat": hb, "composite": comp})
    with open(history_path, "w") as f:
        json.dump(history[-10:], f, indent=2)  # keep last 10

if __name__ == "__main__":
    main()
