"""
Test the 3x replication gate in isolation.

Run: python test_replication_gate.py
"""
import statistics
from close_loop_runner import CloseLoopRunner
from crab import log


def mock_golden_eval(simulated_scores: dict[str, float]):
    """Return a stable copy each call."""
    return dict(simulated_scores)


def test_replication_gate_passes():
    """All 3 passes improve -> should commit."""
    runner = CloseLoopRunner()

    # Simulate baseline
    baseline = {"accuracy": 0.70, "speed": 0.60}

    # Mock the eval to return consistent improvements
    improvement = 0.05
    pass1 = {"accuracy": 0.755, "speed": 0.655}
    pass2 = {"accuracy": 0.752, "speed": 0.652}
    pass3 = {"accuracy": 0.758, "speed": 0.653}

    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return [baseline, pass1, pass2, pass3][call_count[0] - 1]

    train_fn_called = [False]
    def mock_train():
        train_fn_called[0] = True
        return {"ok": True}

    result = runner._run_with_replication_gate(
        manifest_path=None,  # won't write
        train_fn=mock_train,
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,
        required_passes=3,
    )

    assert result["status"] == "reproduced", f"Expected reproduced, got {result['status']}"
    assert result["committed"] is True
    assert train_fn_called[0] is True
    log("✓ test_replication_gate_passes PASSED")


def test_replication_gate_one_drop():
    """One pass drops -> should reject."""
    runner = CloseLoopRunner()

    baseline = {"accuracy": 0.70}
    # Pass 2 drops
    pass1 = {"accuracy": 0.76}
    pass2 = {"accuracy": 0.68}  # DROP
    pass3 = {"accuracy": 0.75}

    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return [baseline, pass1, pass2, pass3][call_count[0] - 1]

    result = runner._run_with_replication_gate(
        manifest_path=None,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,
        required_passes=3,
    )

    assert result["status"] == "pending_diagnosis", f"Expected pending_diagnosis, got {result['status']}"
    assert result["committed"] is False
    log("✓ test_replication_gate_one_drop PASSED")


def test_replication_gate_jitter_burst():
    """All improve but jitter too high -> reject."""
    runner = CloseLoopRunner()

    baseline = {"accuracy": 0.70}
    # Huge variance despite all > baseline
    pass1 = {"accuracy": 0.90}
    pass2 = {"accuracy": 0.72}
    pass3 = {"accuracy": 0.71}

    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return [baseline, pass1, pass2, pass3][call_count[0] - 1]

    result = runner._run_with_replication_gate(
        manifest_path=None,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,  # 15% max jitter
        required_passes=3,
    )

    assert result["status"] == "pending_diagnosis", f"Expected pending_diagnosis, got {result['status']}"
    assert result["committed"] is False
    # Jitter for pass1 vs rest is huge
    log(f"Jitter check: {result['dimension_results']}")
    log("✓ test_replication_gate_jitter_burst PASSED")


def test_replication_gate_mean_too_small():
    """All improve but mean_delta < min_improvement -> reject."""
    runner = CloseLoopRunner()

    baseline = {"accuracy": 0.70}
    # Tiny improvements
    pass1 = {"accuracy": 0.701}
    pass2 = {"accuracy": 0.702}
    pass3 = {"accuracy": 0.703}

    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return [baseline, pass1, pass2, pass3][call_count[0] - 1]

    result = runner._run_with_replication_gate(
        manifest_path=None,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,  # needs 1% improvement
        max_std_ratio=0.15,
        required_passes=3,
    )

    assert result["status"] == "pending_diagnosis"
    assert result["committed"] is False
    log("✓ test_replication_gate_mean_too_small PASSED")


if __name__ == "__main__":
    test_replication_gate_passes()
    test_replication_gate_one_drop()
    test_replication_gate_jitter_burst()
    test_replication_gate_mean_too_small()
    log("\n✓ All replication gate tests passed")
