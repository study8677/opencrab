#!/usr/bin/env python3
"""Direct execution of fitness ledger components."""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))

def main():
    # Import components
    from arena import Arena, save_results, load_results
    from boundaryeval import BoundaryEval
    from regression import RegressionSuite
    from canary import Canary
    
    print("=" * 70)
    print("FITNESS LEDGER EXECUTION")
    print("=" * 70)
    
    # Setup directories
    base = "state/fitness"
    for sub in ["", "arena", "boundaryeval", "regression", "canary", "meta"]:
        os.makedirs(f"{base}/{sub}" if sub else base, exist_ok=True)
    
    # 1. Arena Evaluation
    print("\n[ARENA] Head-to-head capability evaluation...")
    arena = Arena()
    agents = ["brainonly_default", "claude_p_default", "weaning_brainonly", "handoff_relay"]
    tasks = ["health", "consistency", "autonomy", "throughput", "safety", "drift", "conflict", "patch"]
    
    arena_results = arena.run(agents, tasks)
    arena_file = f"{base}/arena/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    arena.save_results(arena_results, arena_file)
    arena.save_results(arena_results, f"{base}/arena/latest.json")
    print(f"  ✓ Arena complete - {len(agents)} agents, {len(tasks)} tasks")
    print(f"    Scores: {json.dumps(arena_results['scores'], indent=4)}")
    
    # 2. Boundary Evaluation  
    print("\n[BOUNDARYEVAL] Constraint boundary checking...")
    boundary = BoundaryEval()
    dimensions = ["safety_threshold", "autonomy_ceiling", "consistency_floor", 
                  "drift_latency", "patch_contract", "external_risk", "malicious_exposure"]
    
    boundary_results = boundary.evaluate(dimensions)
    boundary.save_results(boundary_results, f"{base}/boundaryeval/latest.json")
    violations = boundary_results.get("violations", [])
    print(f"  ✓ Boundary eval complete - {len(dimensions)} dimensions")
    print(f"    Violations: {violations if violations else 'None'}")
    for dim in dimensions:
        score = boundary_results["scores"].get(dim, {}).get("value", 0)
        print(f"      {dim}: {score:.1f}")
    
    # 3. Regression Suite
    print("\n[REGRESSION] Test suite execution...")
    regression = RegressionSuite()
    suites = ["health_sanity", "consistency_assertions", "autonomy_measurement",
              "throughput_baseline", "safety_invariants", "drift_regression"]
    
    for suite in suites:
        regression.run_suite(suite)
    
    regression_results = regression.run_all()
    regression_file = f"{base}/regression/run_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    with open(regression_file, "w") as f:
        json.dump(regression_results, f, indent=2)
    with open(f"{base}/regression/latest.json", "w") as f:
        json.dump(regression_results, f, indent=2)
    
    overall = sum(r.get("pass_rate", 0) for r in regression_results.values()) / len(regression_results)
    print(f"  ✓ Regression complete - {len(suites)} suites")
    print(f"    Overall pass rate: {overall:.1f}%")
    for name, result in regression_results.items():
        print(f"      {name}: {result['pass_rate']:.1f}%")
    
    # 4. Canary Monitoring
    print("\n[CANARY] Health monitoring pulse...")
    canary = Canary()
    metrics = ["health_pulse", "consistency_beat", "autonomy_signal", 
               "throughput_ticker", "safety_watch", "drift_alert"]
    
    for metric in metrics:
        canary.check_metric(metric)
    
    canary_results = canary.check_all()
    health_score = canary.get_health_score()
    
    with open(f"{base}/canary/latest.json", "w") as f:
        json.dump({"metrics": canary_results, "health_score": health_score}, f, indent=2)
    
    print(f"  ✓ Canary complete - {len(metrics)} metrics")
    print(f"    Health score: {health_score:.1f}%")
    for name, data in canary_results.items():
        print(f"      {name}: {data['status']} ({data['health']:.1f})")
    
    # 5. Weakness Analysis
    print("\n[ANALYSIS] Identifying weakest dimensions...")
    weaknesses = []
    
    # Boundary violations
    for dim in violations:
        score = boundary_results["scores"].get(dim, {}).get("value", 0)
        weaknesses.append({
            "source": "boundaryeval",
            "dimension": dim,
            "score": score,
            "threshold": 75,
            "gap": 75 - score,
            "priority": "HIGH"
        })
    
    # Low regression rates
    for name, result in regression_results.items():
        rate = result.get("pass_rate", 0)
        if rate < 70:
            weaknesses.append({
                "source": "regression",
                "dimension": name,
                "score": rate,
                "threshold": 70,
                "gap": 70 - rate,
                "priority": "HIGH" if rate < 60 else "MEDIUM"
            })
    
    # Canary critical/degraded
    for name, data in canary_results.items():
        if data["status"] in ["critical", "degraded"]:
            weaknesses.append({
                "source": "canary",
                "dimension": name,
                "score": data["health"],
                "threshold": 70,
                "gap": 70 - data["health"],
                "priority": "HIGH" if data["status"] == "critical" else "MEDIUM"
            })
    
    # Sort by gap
    weaknesses.sort(key=lambda x: x["gap"], reverse=True)
    
    # Save weakness analysis
    analysis = {
        "timestamp": datetime.now().isoformat(),
        "weakness_count": len(weaknesses),
        "weaknesses": weaknesses
    }
    
    with open(f"{base}/meta/weakness_analysis.json", "w") as f:
        json.dump(analysis, f, indent=2)
    
    # 6. Combined Score
    print("\n[COMBINED] Fitness ledger summary...")
    combined = {
        "timestamp": datetime.now().isoformat(),
        "arena": arena_results,
        "boundaryeval": boundary_results,
        "regression": {
            "suites": regression_results,
            "overall_pass_rate": overall
        },
        "canary": {
            "metrics": canary_results,
            "health_score": health_score
        },
        "weakness_analysis": analysis
    }
    
    with open(f"{base}/combined.json", "w") as f:
        json.dump(combined, f, indent=2)
    
    # Final output
    print("\n" + "=" * 70)
    print("FITNESS LEDGER EXECUTION COMPLETE")
    print("=" * 70)
    
    print(f"\n📊 COMBINED FITNESS SCORES:")
    print(f"   Regression: {overall:.1f}%")
    print(f"   Canary: {health_score:.1f}%")
    print(f"   Boundary Violations: {len(violations)}")
    print(f"   Total Weaknesses: {len(weaknesses)}")
    
    if weaknesses:
        print(f"\n🎯 PRIORITY WEAKNESSES (work queue):")
        for i, w in enumerate(weaknesses[:5], 1):
            print(f"   {i}. [{w['source']}] {w['dimension']}")
            print(f"      Score: {w['score']:.1f} | Gap: {w['gap']:.1f} | Priority: {w['priority']}")
    
    print(f"\n📁 Results saved to: {base}/")
    print(f"   - arena/latest.json")
    print(f"   - boundaryeval/latest.json")
    print(f"   - regression/latest.json")
    print(f"   - canary/latest.json")
    print(f"   - combined.json")
    print(f"   - meta/weakness_analysis.json")
    
    return combined

if __name__ == "__main__":
    main()
