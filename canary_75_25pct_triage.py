"""
Triage script: for each failure in canary_75, produce a quick diagnostic line.
Run after you have failure data. Categorizes into:
  - A: External dependency
  - B: Deep logic (brain-only blind)
  - C: Flaky
  - D: Unknown
"""
import json
import os
import sys
from pathlib import Path

def find_failing_cases():
    """Locate canary_75 failure data from multiple possible sources."""
    sources = []

    # JSONL files
    for pattern in ["*canary*75*.jsonl", "*canary*75*.json", "results/*canary*.jsonl"]:
        for p in Path(".").glob(pattern):
            if p.is_file():
                sources.append(p)
        for p in Path("results").glob(pattern.replace("results/", "")):
            if p.is_file() and p not in sources:
                sources.append(p)

    # Also check logs/
    if Path("logs").exists():
        for p in Path("logs").glob("*canary*75*"):
            if p not in sources:
                sources.append(p)

    return sources

def triage_case(case_data):
    """Classify a single failing case."""
    # Collect all text fields for pattern matching
    text_parts = []
    for v in case_data.values():
        if isinstance(v, str):
            text_parts.append(v.lower())
        elif isinstance(v, (list, tuple)):
            for item in v:
                if isinstance(item, str):
                    text_parts.append(item.lower())

    combined = " ".join(text_parts)

    # Type A: External dependencies
    type_a_keywords = [
        "network", "timeout", "connection refused", "http", "ssl",
        "certificate", "dns", "proxy", "rate limit", "429",
        "openai", "anthropic", "api", "key", "secret",
        "no such file", "file not found", "permission denied",
        "import error", "modulenotfounderror", "importerror",
        "subprocess", "exec", "command not found",
        "real model", "真实模型", "gpt", "claude",
    ]

    # Type B: Deep logic / brain-only blind spots
    type_b_keywords = [
        "ast", "syntax tree", "parse error", "indentation",
        "multi-file", "multi-module", "cross-file", "side effect",
        "import order", "cyclic", "circular import",
        "semantic", "type error", "logical error", "wrong logic",
        "edge case", "corner case", "boundary condition",
        "nondeterministic", "random", "seed",
        "overfit", "over-fitting", "too specific",
    ]

    # Type C: Reproducibility / flakiness
    type_c_keywords = [
        "flaky", "intermittent", "sometimes", "unstable",
        "race condition", "timing", "concurrent",
        "jitter", "non-deterministic",
    ]

    for kw in type_a_keywords:
        if kw in combined:
            return "A", f"External dependency: {kw}"

    for kw in type_b_keywords:
        if kw in combined:
            return "B", f"Deep logic issue: {kw}"

    for kw in type_c_keywords:
        if kw in combined:
            return "C", f"Reproducibility issue: {kw}"

    return "D", "Unknown - needs manual diagnosis"

def main():
    sources = find_failing_cases()

    if not sources:
        print("ERROR: No canary_75 failure data found.")
        print("Run canary_75 first, then run this triage script.")
        print("\nTry: python run_canary_75_final.py")
        return

    print(f"Found {len(sources)} potential data sources\n")

    all_failures = []
    for source in sources:
        print(f"Loading: {source}")
        try:
            if source.suffix == ".jsonl":
                with open(source) as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            all_failures.append(json.loads(line))
            else:
                with open(source) as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        all_failures.extend(data)
                    else:
                        all_failures.append(data)
        except Exception as e:
            print(f"  Error loading {source}: {e}")

    print(f"\nTotal records loaded: {len(all_failures)}")

    if not all_failures:
        print("No data. Exiting.")
        return

    # Filter to failures
    failures = []
    for rec in all_failures:
        status = rec.get("status") or rec.get("result") or rec.get("passed")
        if isinstance(status, bool):
            if not status:
                failures.append(rec)
        elif isinstance(status, str):
            if status.lower() not in ("pass", "success", "passed"):
                failures.append(rec)
        else:
            score = rec.get("score", 1.0)
            if score < 0.75:
                failures.append(rec)

    print(f"Failures: {len(failures)} / {len(all_failures)}")
    print(f"Success rate: {(len(all_failures)-len(failures))/len(all_failures)*100:.1f}%\n")

    if not failures:
        print("No failures found. Canary 75 may already be at or above target.")
        return

    # Triage each failure
    type_a, type_b, type_c, type_d = [], [], [], []

    print("=" * 70)
    print(f"TRIAGE OF {len(failures)} FAILURE CASES")
    print("=" * 70)

    for i, failure in enumerate(failures):
        cat, note = triage_case(failure)
        case_id = failure.get("case_id") or failure.get("id") or failure.get("task_id") or f"case_{i}"

        triage_entry = {"case": case_id, "category": cat, "note": note, "record": failure}

        if cat == "A":
            type_a.append(triage_entry)
        elif cat == "B":
            type_b.append(triage_entry)
        elif cat == "C":
            type_c.append(triage_entry)
        else:
            type_d.append(triage_entry)

    # Print summary
    for label, entries in [("A: External Dependency", type_a),
                            ("B: Deep Logic (brain-only blind)", type_b),
                            ("C: Reproducibility", type_c),
                            ("D: Unknown", type_d)]:
        if entries:
            print(f"\n### {label} ({len(entries)} cases) ###")
            for e in entries:
                print(f"  [{e['case']}] {e['note']}")

    # Final verdict
    print("\n" + "=" * 70)
    print("VERDICT")
    print("=" * 70)

    total = len(failures)
    print(f"\nType A (External): {len(type_a)} ({len(type_a)/total*100:.0f}%)")
    print(f"Type B (Deep Logic): {len(type_b)} ({len(type_b)/total*100:.0f}%)")
    print(f"Type C (Flaky): {len(type_c)} ({len(type_c)/total*100:.0f}%)")
    print(f"Type D (Unknown): {len(type_d)} ({len(type_d)/total*100:.0f}%)")

    # Strategic recommendation
    print("\n--- Strategic Recommendation ---")
    if len(type_b) + len(type_d) >= total * 0.6:
        print(">>> Majority are Type-B (deep logic) or Unknown.")
        print(">>> These are NOT fixable by brain-only improvements.")
        print(">>> RECOMMEND: Shift target to boundaryeval / arena")
        print(">>> Those have softer baselines and give real fitness gains.")
    elif len(type_a) >= total * 0.5:
        print(">>> Majority are Type-A (external dependency).")
        print(">>> These need mocking, external service, or test environment fixes.")
        print(">>> RECOMMEND: Mock external calls or accept these as environment issues.")
    elif len(type_c) >= total * 0.3:
        print(">>> Significant Type-C (flaky) failures.")
        print(">>> RECOMMEND: Stabilize reproducibility before targeting 80%.")
    else:
        print(">>> Mixed distribution. Need targeted fixes per category.")

    # Save detailed triage
    triage_report = {
        "total": total,
        "type_a_count": len(type_a),
        "type_b_count": len(type_b),
        "type_c_count": len(type_c),
        "type_d_count": len(type_d),
        "type_a_examples": [{"case": e["case"], "note": e["note"]} for e in type_a[:5]],
        "type_b_examples": [{"case": e["case"], "note": e["note"]} for e in type_b[:5]],
        "type_c_examples": [{"case": e["case"], "note": e["note"]} for e in type_c[:5]],
        "type_d_examples": [{"case": e["case"], "note": e["note"]} for e in type_d[:5]],
        "recommendation": (
            "shift_to_boundaryeval" if len(type_b) + len(type_d) >= total * 0.6
            else "fix_external_deps" if len(type_a) >= total * 0.5
            else "stabilize_reproducibility" if len(type_c) >= total * 0.3
            else "mixed_needs_targeted_fixes"
        ),
    }

    with open("canary_75_25pct_triage.json", "w") as f:
        json.dump(triage_report, f, indent=2)

    print(f"\nTriage report saved: canary_75_25pct_triage.json")

if __name__ == "__main__":
    main()
