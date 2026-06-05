# Fitness Replication Gate

## Problem

Previous fitness闭环 only verified improvement **once** before writing delta to manifest. This is the same pattern as "fake progress / fake slimming" — a single data point dressed up as a trend.

## Solution

**3x Replication Gate**: statistical honesty by requiring all 3 passes to pass before committing.

```
┌─────────────────────────────────────────────────────┐
│  1. Read manifest → find weakest dimension           │
│  2. Run train_weakness on that dimension            │
│  3. Run golden eval 3 times                          │
│  4. Gate check:                                      │
│     ✓ ALL 3 improve (no drops)                      │
│     ✓ mean_delta ≥ 1% (real lift, not noise)        │
│     ✓ jitter = std(Δ)/|mean(Δ)| ≤ 15%             │
│  5. ALL conditions met → commit delta, mark verified │
│     ANY condition fails → reject, mark pending_diagnosis │
└─────────────────────────────────────────────────────┘
```

## Key Metrics

| Metric | Formula | Pass Threshold |
|--------|---------|----------------|
| all_improved | all(v > baseline for v in post_vals) | True |
| mean_delta | mean(post_vals - baseline) | ≥ 1% |
| jitter_ratio | stdev(deltas) / \|mean(deltas)\| | ≤ 15% |

## Files

- `fitness_replication_protocol.py` — core protocol, standalone callable
- `close_loop_runner.py` — integrates gate into close_loop.run()
- `test_replication_gate.py` — unit tests
- `regression_replication_gate.py` — pytest regression suite
- `replication_gate_drill.py` — drill scenarios for manual validation

## Why 3 passes?

- 1 pass = single observation, easily fakeable
- 2 passes = can detect gross drops but still vulnerable to noise
- 3 passes = enough to compute std, detect jitter, and be a "statistical event" not a "single point"

## Trust vs Verification

The gate verifies **consistency of pattern**, not correctness of the underlying evaluation. If the eval itself is brainonly-generated fake data, the gate cannot detect that. That is a separate problem addressed by:
- diversity of eval sources
- external validation
- human spot-checks

The gate's job is to ensure that whatever the eval reports, it reports it **reliably** 3 times.

## CLI Usage

```bash
python fitness_replication_protocol.py \
  --crab-path /path/to/crab \
  --min-improvement 0.01 \
  --max-std-ratio 0.15 \
  --required-passes 3
```
