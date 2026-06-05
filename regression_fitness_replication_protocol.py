"""
Regression: fitness_replication_protocol.py

pytest regression_fitness_replication_protocol.py -v
"""
import pytest
import json
import statistics
from pathlib import Path

from fitness_replication_protocol import (
    run_fitness_闭环_with_gate,
    jitter_ratio,
)


def test_jitter_ratio():
    assert abs(jitter_ratio([0.05, 0.05, 0.05])) < 0.01
    assert abs(jitter_ratio([0.05, 0.05, 0.10])) > 0.3
    assert jitter_ratio([0.0]) == 0.0


def test_replication_gate_commits_on_consistent_improvement(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.755},
        {"accuracy": 0.752},
        {"accuracy": 0.758},
    ]
    call_count = [0]
    def eval_fn():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    result = run_fitness_闭环_with_gate(
        crab_path=tmp_path,
        train_fn=lambda: {},
        eval_fn=eval_fn,
        manifest_path=manifest,
        write_manifest=True,
    )
    assert result["committed"] is True
    assert result["status"] == "reproduced"


def test_replication_gate_rejects_drop(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.76},
        {"accuracy": 0.68},
        {"accuracy": 0.75},
    ]
    call_count = [0]
    def eval_fn():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    result = run_fitness_闭环_with_gate(
        crab_path=tmp_path,
        train_fn=lambda: {},
        eval_fn=eval_fn,
        manifest_path=manifest,
    )
    assert result["committed"] is False
    assert result["status"] == "pending_diagnosis"


def test_manifest_verified_flag_set_on_commit(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.755},
        {"accuracy": 0.752},
        {"accuracy": 0.758},
    ]
    call_count = [0]
    def eval_fn():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    run_fitness_闭环_with_gate(
        crab_path=tmp_path,
        train_fn=lambda: {},
        eval_fn=eval_fn,
        manifest_path=manifest,
        write_manifest=True,
    )

    data = json.loads(manifest.read_text())
    assert data["fitness"]["dimensions"]["accuracy"]["verified"] is True
    assert data["fitness"]["dimensions"]["accuracy"]["replication_passes"] == 3


def test_pending_diagnosis_on_reject(tmp_path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text("{}")

    scores = [
        {"accuracy": 0.70},
        {"accuracy": 0.76},
        {"accuracy": 0.68},
        {"accuracy": 0.75},
    ]
    call_count = [0]
    def eval_fn():
        call_count[0] += 1
        return scores[call_count[0] - 1]

    run_fitness_闭环_with_gate(
        crab_path=tmp_path,
        train_fn=lambda: {},
        eval_fn=eval_fn,
        manifest_path=manifest,
        write_manifest=True,
    )

    data = json.loads(manifest.read_text())
    assert data["pending_diagnosis"]["replication_status"] == "failed"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
