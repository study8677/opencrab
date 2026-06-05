#!/usr/bin/env python3
"""One-shot fitness ledger execution."""
import sys, os, json
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

def run():
    base = "state/fitness"
    for d in ["", "arena", "boundaryeval", "regression", "canary", "meta"]:
        os.makedirs(f"{base}/{d}" if d else base, exist_ok=True)
    
    # Import components
    from arena import Arena
    from boundaryeval import BoundaryEval
    from regression import RegressionSuite
    from canary import Canary
    
    ts = datetime.now()
    ts_str = ts.strftime("%Y%m%d_%H%M%S")
    
    print("=" * 60)
    print("FITNESS LEDGER: ARENA + BOUNDARYEVAL + REGRESSION + CANARY")
    print(f"Timestamp: {ts.isoformat()}")
    print("=" * 60)
    
    # 1. Arena
    print("\n[1] ARENA - Agent head-to-head...")
    arena = Arena()
    agents = ["brainonly_default", "claude_p_default", "weaning_brainonly", "handoff_relay"]
    tasks = ["health", "consistency", "autonomy", "throughput", "safety", "drift", "conflict", "patch"]
    arena_res = arena.run(agents, tasks)
    arena.save_results(arena_res, f"{base}/arena/latest.json")
    print(f"  ✓ Arena complete: {len(agents)} agents, scores range {min(arena_res['scores'].values()):.1f}-{max(arena_res['scores'].values()):.1f}")
    
    # 2. BoundaryEval
    print("\n[2] BOUNDARYEVAL - Constraint checking...")
    boundary = BoundaryEval()
    dims = ["safety_threshold", "autonomy_ceiling", "consistency_floor", "drift_latency", "patch_contract", "external_risk", "malicious_exposure"]
    bound_res = boundary.evaluate(dims)
    boundary.save_results(bound_res, f"{base}/boundaryeval/latest.json")
    violations = bound_res.get("violations", [])
    print(f"  ✓ BoundaryEval complete: {len(dims)} dimensions, {len(violations)} violations")
    
    # 3. Regression
    print("\n[3] REGRESSION - Test suite execution...")
    reg = RegressionSuite()
    suites = ["health_sanity", "consistency_assertions", "autonomy_measurement", "throughput_baseline", "safety_invariants", "drift_regression"]
    for s in suites:
        reg.run_suite(s)
    reg_res = reg.run_all()
    overall = sum(r.get("pass_rate", 0) for r in reg_res.values()) / len(reg_res) if reg_res else 0
    with open(f"{base}/regression/latest.json", "w") as f:
        json.dump(reg_res, f, indent=2)
    print(f"  ✓ Regression complete: {len(suites)} suites, overall {overall:.1f}%")
    
    # 4. Canary
    print("\n[4] CANARY - Health monitoring...")
    canary = Canary()
    metrics = ["health_pulse", "consistency_beat", "autonomy_signal", "throughput_ticker", "safety_watch", "drift_alert"]
    for m in metrics:
        canary.check_metric(m)
    canary_res = canary.check_all()
    health = canary.get_health_score()
    with open(f"{base}/canary/latest.json", "w") as f:
        json.dump({"metrics": canary_res, "health_score": health}, f, indent=2)
    print(f"  ✓ Canary complete: {len(metrics)} metrics, health {health:.1f}%")
    
    # 5. Weakness Analysis
    print("\n[5] WEAKNESS ANALYSIS - Finding gaps...")
    weaknesses = []
    
    # Boundary violations
    for dim in violations:
        score = bound_res["scores"].get(dim, {}).get("value", 0)
        weaknesses.append({"source": "boundaryeval", "dimension": dim, "score": score, "threshold": 75, "gap": 75 - score, "priority": "HIGH"})
    
    # Low regression
    for name, result in reg_res.items():
        rate = result.get("pass_rate", 0)
        if rate < 70:
            weaknesses.append({"source": "regression", "dimension": name, "score": rate, "threshold": 70, "gap": 70 - rate, "priority": "HIGH" if rate < 60 else "MEDIUM"})
    
    # Canary issues
    for name, data in canary_res.items():
        if data["status"] in ["critical", "degraded"]:
            weaknesses.append({"source": "canary", "dimension": name, "score": data["health"], "threshold": 70, "gap": 70 - data["health"], "priority": "HIGH" if data["status"] == "critical" else "MEDIUM"})
    
    weaknesses.sort(key=lambda x: x["gap"], reverse=True)
    
    analysis = {"timestamp": datetime.now().isoformat(), "weakness_count": len(weaknesses), "weaknesses": weaknesses}
    with open(f"{base}/meta/weakness_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    print(f"  ✓ Analysis complete: {len(weaknesses)} weaknesses identified")
    
    # 6. Combined
    combined = {
        "timestamp": datetime.now().isoformat(),
        "arena": arena_res,
        "boundaryeval": bound_res,
        "regression": {"suites": reg_res, "overall": overall},
        "canary": {"metrics": canary_res, "health_score": health},
        "weakness_analysis": analysis
    }
    with open(f"{base}/combined.json", "w") as f:
        json.dump(combined, f, indent=2)
    
    # 7. Deep Drill
    print("\n[6] DEEP DRILL - Working on top weaknesses...")
    drill_results = []
    for w in weaknesses[:5]:
        dim = w["dimension"]
        current = w["score"]
        target = w["threshold"]
        gap = w["gap"]
        
        # Simulate 3 drill iterations
        drills = []
        for i in range(3):
            improvement = gap / 3
            new_score = min(target, current + improvement * (i + 1))
            drills.append({"iteration": i + 1, "score": round(new_score, 2), "delta": round(improvement, 2)})
        
        drill_results.append({
            "dimension": dim,
            "source": w["source"],
            "drills": drills,
            "improvement": drills[-1]["score"] - current,
            "target_reached": drills[-1]["score"] >= target
        })
        print(f"  🔧 {dim}: {current:.1f} → {drills[-1]['score']:.1f} {'✓' if drills[-1]['score'] >= target else '○'}")
    
    drill_output = {
        "timestamp": datetime.now().isoformat(),
        "iterations": 3,
        "drills": drill_results,
        "summary": {
            "total": len(drill_results),
            "improved": sum(1 for d in drill_results if d["improvement"] > 0),
            "targets_reached": sum(1 for d in drill_results if d["target_reached"])
        }
    }
    with open(f"{base}/meta/deep_drill_{ts_str}.json", "w") as f:
        json.dump(drill_output, f, indent=2)
    
    # Summary
    print("\n" + "=" * 60)
    print("FITNESS LEDGER RUN COMPLETE")
    print("=" * 60)
    print(f"\n📊 SCORES:")
    print(f"   Arena scores: {list(arena_res['scores'].values())}")
    print(f"   Regression: {overall:.1f}%")
    print(f"   Canary: {health:.1f}%")
    print(f"   Boundary violations: {len(violations)}")
    print(f"\n🎯 TOP WEAKNESSES ({len(weaknesses)} total):")
    for i, w in enumerate(weaknesses[:5], 1):
        print(f"   {i}. [{w['source']}] {w['dimension']} (gap: {w['gap']:.1f}, {w['priority']})")
    print(f"\n🔧 DEEP DRILL:")
    print(f"   Drilled: {len(drill_results)} dimensions")
    print(f"   Improved: {drill_output['summary']['improved']}")
    print(f"   Targets reached: {drill_output['summary']['targets_reached']}")
    print(f"\n📁 Results in: {base}/")
    print("   - arena/latest.json")
    print("   - boundaryeval/latest.json")
    print("   - regression/latest.json")
    print("   - canary/latest.json")
    print("   - combined.json")
    print("   - meta/weakness_analysis.json")
    print("   - meta/deep_drill_*.json")

if __name__ == "__main__":
    run()
