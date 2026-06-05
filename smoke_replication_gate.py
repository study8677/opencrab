"""
Smoke test: python smoke_replication_gate.py
Quick sanity check the 3x replication gate module imports and basic logic works.
"""
import sys


def main():
    print("=" * 60)
    print("smoke: replication_gate")
    print("=" * 60)

    # 1. Import all new modules
    print("\n[1] Importing modules...")
    try:
        from fitness_replication_protocol import run_fitness_闭环_with_gate, jitter_ratio
        print("  ✓ fitness_replication_protocol")
    except Exception as e:
        print(f"  ✗ fitness_replication_protocol: {e}")
        sys.exit(1)

    try:
        from close_loop_runner import CloseLoopRunner
        print("  ✓ close_loop_runner")
    except Exception as e:
        print(f"  ✗ close_loop_runner: {e}")
        sys.exit(1)

    try:
        from replication_gate_drill import replication_gate
        print("  ✓ replication_gate_drill")
    except Exception as e:
        print(f"  ✗ replication_gate_drill: {e}")
        sys.exit(1)

    # 2. jitter_ratio sanity
    print("\n[2] jitter_ratio sanity...")
    assert jitter_ratio([0.05, 0.05, 0.05]) < 0.01
    assert jitter_ratio([0.05, 0.10, 0.15]) > 0.5
    print("  ✓ jitter_ratio computes correctly")

    # 3. replication_gate core logic with mock
    print("\n[3] Core gate logic...")
    from replication_gate_drill import replication_gate

    baseline = {"accuracy": 0.70}
    post_scores = [
        {"accuracy": 0.755},
        {"accuracy": 0.752},
        {"accuracy": 0.758},
    ]
    result = replication_gate(baseline, post_scores)
    assert result["accepted"] is True
    assert result["status"] == "reproduced"
    print(f"  ✓ Consistent improvement passes gate: {result['status']}")

    # 4. Reject drop
    print("\n[4] Reject single drop...")
    baseline = {"accuracy": 0.70}
    post_scores = [
        {"accuracy": 0.76},
        {"accuracy": 0.68},  # DROP
        {"accuracy": 0.75},
    ]
    result = replication_gate(baseline, post_scores)
    assert result["accepted"] is False
    print(f"  ✓ Single drop rejected: {result['status']}")

    # 5. CloseLoopRunner._pick_weakest_dimension (no manifest = returns None)
    print("\n[5] CloseLoopRunner instantiation...")
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as tmpdir:
        runner = CloseLoopRunner(crab_path=Path(tmpdir))
        weakest = runner._pick_weakest_dimension()
        print(f"  ✓ _pick_weakest_dimension with no manifest returns: {weakest}")

    print("\n" + "=" * 60)
    print("✓ ALL smoke checks passed")
    print("=" * 60)


if __name__ == "__main__":
    main()
