## 3x Replication Gate for Fitness闭环

**Date**: today
**Impact**: Fitness闭环 now requires statistical confirmation before writing delta to manifest.

### What changed

- `close_loop_runner.py`: `run()` now calls `_run_with_replication_gate()` which:
  1. Reads baseline from evalbench golden set
  2. Runs `train_weakness` on the weakest dimension
  3. Re-tests 3 times
  4. Only commits if ALL conditions hold:
     - `all(v > baseline for v in post_vals)` — no drops
     - `mean_delta >= 1%` — real lift
     - `jitter = std(deltas) / |mean(deltas)| <= 15%` — no jitter burst
  5. Otherwise marks manifest with `pending_diagnosis`

- `fitness_replication_protocol.py`: Standalone protocol for callers who want the gate without the runner.

- `test_replication_gate.py`, `regression_replication_gate.py`: Test suites.

- `replication_gate_drill.py`: Drill scenarios for manual validation.

### Why

Single-pass confirmation is the same pattern as "fake progress / fake slimming" — one data point dressed as a trend. The 3x gate upgrades "improvement" from a single observation to a statistical event.

### Parameters

| Param | Default | Meaning |
|-------|---------|---------|
| `--min-improvement` | 0.01 | 1% minimum mean delta |
| `--max-std-ratio` | 0.15 | 15% max jitter |
| `--required-passes` | 3 | Number of re-test passes |

CLI: `python fitness_replication_protocol.py --crab-path . --min-improvement 0.01`
