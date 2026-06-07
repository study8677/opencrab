#!/usr/bin/env python3
"""
Compare 3x brain-only patch results across recent runs.
Output: side-by-side table + verdict.
"""
import json
import sys
from pathlib import Path

# --- config ---
BASE = Path(".")
RUNS = [
    ("canary_75_3x", BASE / "reproduce_canary_75_3x.jsonl"),
    ("canary_3x",    BASE / "reproduce_canary_3x.jsonl"),
]
SUMMARY_FILE = BASE / "canary_brainonly_3x_summary.json"

def load_runs():
    """Load each run's jsonl into list of dicts."""
    results = {}
    for name, path in RUNS:
        entries = []
        if path.exists():
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        results[name] = entries
    return results

def extract_scores(entries):
    """Return dict: scenario -> (baseline, patched, delta) or None."""
    data = {}
    for e in entries:
        scenario = e.get("scenario", e.get("name", "?"))
        baseline = e.get("baseline_score", e.get("baseline", None))
        patched  = e.get("patched_score",  e.get("patched",  None))
        if baseline is not None and patched is not None:
            delta = patched - baseline
            data[scenario] = {"baseline": baseline, "patched": patched, "delta": delta}
    return data

def print_row(label, values, widths):
    parts = [f"{v:<{w}}" for v, w in zip([label] + values, widths)]
    print(" | ".join(parts))

def main():
    print("=" * 70)
    print("CANARY BRAIN-ONLY 3x COMPARISON")
    print("=" * 70)

    all_data = load_runs()

    # collect all scenarios
    all_scenarios = set()
    for name, entries in all_data.items():
        for e in entries:
            s = e.get("scenario", e.get("name", "?"))
            all_scenarios.add(s)

    scenarios = sorted(all_scenarios)

    # build per-scenario tables
    headers = ["Scenario"] + [name for name, _ in RUNS]
    widths  = [max(20, max(len(h) for h in headers))] + [18, 18]

    print()
    print("BASELINE scores:")
    print("-" * 70)
    print_row(headers[0], headers[1:], widths)
    print("-" * 70)
    for s in scenarios:
        row = [s]
        for name, _ in RUNS:
            entries = all_data.get(name, [])
            sc_data = extract_scores(entries)
            val = sc_data.get(s, {}).get("baseline", "N/A")
            row.append(f"{val:.3f}" if isinstance(val, float) else str(val))
        print_row(row[0], row[1:], widths)

    print()
    print("PATCHED scores:")
    print("-" * 70)
    print_row(headers[0], headers[1:], widths)
    print("-" * 70)
    for s in scenarios:
        row = [s]
        for name, _ in RUNS:
            entries = all_data.get(name, [])
            sc_data = extract_scores(entries)
            val = sc_data.get(s, {}).get("patched", "N/A")
            row.append(f"{val:.3f}" if isinstance(val, float) else str(val))
        print_row(row[0], row[1:], widths)

    print()
    print("DELTA (patched - baseline):")
    print("-" * 70)
    print_row(headers[0], headers[1:], widths)
    print("-" * 70)
    for s in scenarios:
        row = [s]
        for name, _ in RUNS:
            entries = all_data.get(name, [])
            sc_data = extract_scores(entries)
            val = sc_data.get(s, {}).get("delta", None)
            if val is None:
                row.append("N/A")
            elif val >= 0:
                row.append(f"+{val:.3f}")
            else:
                row.append(f"{val:.3f}")
        print_row(row[0], row[1:], widths)

    # aggregate summary
    print()
    print("AGGREGATE SUMMARY")
    print("-" * 70)
    summary = {}
    for name, _ in RUNS:
        entries = all_data.get(name, [])
        sc_data = extract_scores(entries)
        if sc_data:
            deltas = [v["delta"] for v in sc_data.values()]
            avg_delta = sum(deltas) / len(deltas) if deltas else 0
            pos = sum(1 for d in deltas if d > 0)
            neg = sum(1 for d in deltas if d < 0)
            summary[name] = {
                "scenarios": len(scenarios),
                "avg_delta": avg_delta,
                "positive": pos,
                "negative": neg,
                "neutral":  len(deltas) - pos - neg,
            }
            print(f"  {name}: avg_delta={avg_delta:+.3f}  ↑{pos} ↓{neg} ={len(deltas)-pos-neg}")
        else:
            print(f"  {name}: NO DATA")

    # verdict
    print()
    print("VERDICT")
    print("-" * 70)
    if summary:
        best = max(summary.items(), key=lambda x: x[1]["avg_delta"])
        worst = min(summary.items(), key=lambda x: x[1]["avg_delta"])
        print(f"  BEST  : {best[0]}  (avg_delta={best[1]['avg_delta']:+.3f})")
        print(f"  WORST : {worst[0]}  (avg_delta={worst[1]['avg_delta']:+.3f})")

        # decision logic
        best_delta = best[1]["avg_delta"]
        if best_delta > 0.05:
            print(f"  -> RECOMMEND: keep patching (real improvement)")
        elif best_delta > 0.0:
            print(f"  -> RECOMMEND: marginal gain, consider refinement")
        else:
            print(f"  -> RECOMMEND: no gain, try different approach")

    # save summary
    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSummary saved to {SUMMARY_FILE}")

if __name__ == "__main__":
    main()
