"""
Regression test: ensure the 3x replication gate is enforced.

Run: python -m pytest regression_replication_gate.py -v
"""
import pytest
import statistics
from close_loop_runner import CloseLoopRunner


def test_gate_commits_on_real_improvement(tmp_path):
    """3 consistent passes should commit delta."""
    runner = CloseLoopRunner()
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"fitness": {"dimensions": {"accuracy": 0.70}}}')

    # Return 4 scores: baseline + 3 passes
    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.755},
        {"accuracy": 0.752},
        {"accuracy": 0.758},
    ]
    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    result = runner._run_with_replication_gate(
        manifest_path=manifest,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,
        required_passes=3,
    )
    assert result["committed"] is True
    assert result["status"] == "reproduced"


def test_gate_rejects_on_single_drop(tmp_path):
    """Any pass dropping below baseline should reject."""
    runner = CloseLoopRunner()
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"fitness": {"dimensions": {"accuracy": 0.70}}}')

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.76},
        {"accuracy": 0.68},  # DROP
        {"accuracy": 0.75},
    ]
    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    result = runner._run_with_replication_gate(
        manifest_path=manifest,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,
        required_passes=3,
    )
    assert result["committed"] is False
    assert result["status"] == "pending_diagnosis"


def test_gate_rejects_on_high_jitter(tmp_path):
    """All improve but jitter > threshold should reject."""
    runner = CloseLoopRunner()
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"fitness": {"dimensions": {"accuracy": 0.70}}}')

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.90},  # outlier
        {"accuracy": 0.72},
        {"accuracy": 0.71},
    ]
    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    result = runner._run_with_replication_gate(
        manifest_path=manifest,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,  # 15% max
        required_passes=3,
    )
    assert result["committed"] is False
    jit = result["dimension_results"]["accuracy"]["jitter"]
    assert jit > 0.15, f"Expected jitter > 0.15, got {jit}"


def test_delta_recorded_on_commit(tmp_path):
    """Committed run should have proper delta_record."""
    runner = CloseLoopRunner()
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"fitness": {}}')

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.755},
        {"accuracy": 0.752},
        {"accuracy": 0.758},
    ]
    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    result = runner._run_with_replication_gate(
        manifest_path=manifest,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,
        required_passes=3,
    )
    assert "accuracy" in result["delta"]
    assert result["delta"]["accuracy"]["delta"] > 0
    assert result["delta"]["accuracy"]["std"] >= 0


def test_manifest_written_on_commit(tmp_path):
    """Committed run should persist to manifest."""
    runner = CloseLoopRunner()
    manifest = tmp_path / "manifest.json"
    manifest.write_text('{"fitness": {}}')

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.755},
        {"accuracy": 0.752},
        {"accuracy": 0.758},
    ]
    call_count = [0]
    def mock_eval():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    runner._run_with_replication_gate(
        manifest_path=manifest,
        train_fn=lambda: {},
        golden_eval_fn=mock_eval,
        min_improvement=0.01,
        max_std_ratio=0.15,
        required_passes=3,
    )

    data = __import__("json").loads(manifest.read_text())
    assert "accuracy" in data["fitness"]["dimensions"]
    assert data["fitness"]["dimensions"]["accuracy"]["verified"] is True
    assert data["fitness"]["dimensions"]["accuracy"]["replication_passes"] == 3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
