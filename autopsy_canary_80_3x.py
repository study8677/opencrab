"""
Autopsy for canary 80% 3x consecutive failures.
Purpose: Determine if patch is biased OR if the three gates themselves are jittering.
Goal: Stabilize gates first, then weld.
"""

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from crab import Crab
from check_three_gates import check_three_gates
from check_three_gates_canary import check_three_gates_canary


class Canary80Autopsy:
    """Autopsy 80% 3x consecutive failure to diagnose root cause."""

    def __init__(self, project: str = "main"):
        self.project = project
        self.crab = Crab(project)
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "project": project,
            "diagnosis": None,
            "patch_biased": None,
            "gates_jittering": None,
            "gate_details": {},
            "patch_details": {},
            "recommendation": None,
        }

    def run_autopsy(self, force: bool = False) -> dict:
        """Run full autopsy on canary 80 3x failures."""
        print("=" * 70)
        print("CANARY 80% 3x FAILURE AUTOPSY")
        print("=" * 70)

        # Step 1: Check if 3x failures actually happened
        if not self._check_3x_failure_history(force):
            print("✗ No 3x consecutive failures detected")
            return {"diagnosis": "no_3x_failure"}

        # Step 2: Check three gates status (are they jittering?)
        print("\n[STEP 1] Checking three gates stability...")
        gate_result = self._check_gates_stability()
        self.results["gate_details"] = gate_result

        # Step 3: Analyze patch bias
        print("\n[STEP 2] Analyzing patch bias...")
        patch_result = self._analyze_patch_bias()
        self.results["patch_details"] = patch_result

        # Step 4: Cross-correlate
        print("\n[STEP 3] Cross-correlating gate jitter vs patch bias...")
        self._cross_correlate()

        # Step 5: Generate recommendation
        print("\n[STEP 4] Generating recommendation...")
        self._generate_recommendation()

        self._print_diagnosis()
        self._save_results()

        return self.results

    def _check_3x_failure_history(self, force: bool = False) -> bool:
        """Check if 3x consecutive failures actually occurred."""
        if force:
            return True

        # Check fitness ledger for 3x failures
        ledger_path = Path(f"projects/{self.project}/fitness_ledger.jsonl")
        if not ledger_path.exists():
            return False

        failures = []
        with open(ledger_path) as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("status") == "canary_80_fail":
                    failures.append(entry)

        # Check for 3 consecutive
        if len(failures) >= 3:
            recent = failures[-3:]
            timestamps = [f["timestamp"] for f in recent]
            # Check if within reasonable time window (e.g., 1 hour)
            if self._within_window(timestamps, hours=1):
                self.results["failure_history"] = recent
                return True

        return False

    def _within_window(self, timestamps: list, hours: int = 1) -> bool:
        """Check if timestamps are within window."""
        if len(timestamps) < 2:
            return True
        try:
            t1 = datetime.fromisoformat(timestamps[0])
            t2 = datetime.fromisoformat(timestamps[-1])
            return (t2 - t1) <= timedelta(hours=hours)
        except:
            return True

    def _check_gates_stability(self) -> dict:
        """Check if three gates are stable or jittering."""
        result = {
            "gate_1_fitness": {"stable": None, "variance": None, "samples": []},
            "gate_2_brainonly": {"stable": None, "variance": None, "samples": []},
            "gate_3_evidence": {"stable": None, "variance": None, "samples": []},
            "overall_jitter": None,
        }

        # Get recent gate check results
        for gate_num, gate_name in [(1, "fitness"), (2, "brainonly"), (3, "evidence")]:
            samples = self._get_gate_samples(gate_num)
            if samples:
                result[f"gate_{gate_num}_{gate_name}"]["samples"] = samples
                result[f"gate_{gate_num}_{gate_name}"]["variance"] = self._calc_variance(samples)
                result[f"gate_{gate_num}_{gate_name}"]["stable"] = self._is_stable(samples)

        # Calculate overall jitter
        variances = [v for v in [
            result["gate_1_fitness"]["variance"],
            result["gate_2_brainonly"]["variance"],
            result["gate_3_evidence"]["variance"],
        ] if v is not None]

        if variances:
            result["overall_jitter"] = max(variances) if variances else None
            self.results["gates_jittering"] = result["overall_jitter"] is not None and result["overall_jitter"] > 0.1

        return result

    def _get_gate_samples(self, gate_num: int) -> list:
        """Get recent samples for a specific gate."""
        samples = []
        ledger_path = Path(f"projects/{self.project}/fitness_ledger.jsonl")
        if not ledger_path.exists():
            return samples

        with open(ledger_path) as f:
            for line in f:
                entry = json.loads(line)
                if f"gate_{gate_num}" in entry:
                    samples.append(entry[f"gate_{gate_num}"])
                    if len(samples) >= 10:  # Last 10 samples
                        break
        return samples

    def _calc_variance(self, samples: list) -> Optional[float]:
        """Calculate variance of samples."""
        if len(samples) < 2:
            return None
        try:
            values = [float(s) for s in samples if s is not None]
            if len(values) < 2:
                return None
            mean = sum(values) / len(values)
            variance = sum((x - mean) ** 2 for x in values) / len(values)
            return variance
        except:
            return None

    def _is_stable(self, samples: list, threshold: float = 0.05) -> bool:
        """Check if samples are stable (low variance)."""
        variance = self._calc_variance(samples)
        if variance is None:
            return None
        return variance < threshold

    def _analyze_patch_bias(self) -> dict:
        """Analyze if the patch is biased."""
        result = {
            "patch_history": [],
            "bias_direction": None,
            "bias_magnitude": None,
            "is_biased": None,
        }

        # Get recent patches
        patch_dir = Path(f"projects/{self.project}/patches")
        if patch_dir.exists():
            for patch_file in sorted(patch_dir.glob("*.py"))[-10:]:
                content = patch_file.read_text()
                # Analyze patch characteristics
                bias = self._analyze_single_patch(content)
                result["patch_history"].append({
                    "file": patch_file.name,
                    "bias": bias,
                })

        # Determine overall bias
        biases = [p["bias"] for p in result["patch_history"] if p["bias"] is not None]
        if biases:
            result["bias_direction"] = "converging" if all(b > 0 for b in biases) else \
                                       "diverging" if all(b < 0 for b in biases) else "mixed"
            result["bias_magnitude"] = sum(biases) / len(biases)
            result["is_biased"] = abs(result["bias_magnitude"]) > 0.1

        self.results["patch_biased"] = result["is_biased"]
        return result

    def _analyze_single_patch(self, content: str) -> Optional[float]:
        """Analyze a single patch for bias direction."""
        # Look for common bias patterns
        patterns = {
            "over_relaxed": [r"threshold.*降低", r"lenient", r"relax", r"降低标准"],
            "over_strict": [r"threshold.*提高", r"strict", r"tighten", r"提高标准"],
        }

        scores = {"over_relaxed": 0, "over_strict": 0}
        for direction, pattern_list in patterns.items():
            for pattern in pattern_list:
                if re.search(pattern, content, re.IGNORECASE):
                    scores[direction] += 1

        if scores["over_relaxed"] > scores["over_strict"]:
            return 0.5  # Biased toward relaxation
        elif scores["over_strict"] > scores["over_relaxed"]:
            return -0.5  # Biased toward strictness
        return 0.0

    def _cross_correlate(self) -> None:
        """Cross-correlate gate jitter with patch bias."""
        gates_jittering = self.results.get("gates_jittering", False)
        patch_biased = self.results.get("patch_biased", False)

        if gates_jittering and patch_biased:
            self.results["diagnosis"] = "both_gates_and_patch"
        elif gates_jittering:
            self.results["diagnosis"] = "gates_jitter_only"
        elif patch_biased:
            self.results["diagnosis"] = "patch_bias_only"
        else:
            self.results["diagnosis"] = "unknown"

    def _generate_recommendation(self) -> None:
        """Generate actionable recommendation."""
        diag = self.results.get("diagnosis")
        gate_details = self.results.get("gate_details", {})
        patch_details = self.results.get("patch_details", {})

        if diag == "gates_jitter_only":
            self.results["recommendation"] = {
                "action": "stabilize_gates_first",
                "steps": [
                    "Identify which gate is jittering most",
                    "Add cooldown/circuit-breaker to jittering gate",
                    "Re-run 3x verification",
                    "Only weld after gates are stable",
                ],
                "priority": "GATES_FIRST_THEN_WELD",
            }
        elif diag == "patch_bias_only":
            self.results["recommendation"] = {
                "action": "rebalance_patch",
                "steps": [
                    "Analyze patch bias direction",
                    "Apply counter-patch to rebalance",
                    "Re-run 3x verification",
                    "Weld corrected patch",
                ],
                "priority": "PATCH_REBALANCE_THEN_WELD",
            }
        elif diag == "both_gates_and_patch":
            self.results["recommendation"] = {
                "action": "stabilize_gates_then_rebalance",
                "steps": [
                    "First: Add circuit-breaker to gates",
                    "Second: Wait for gates to stabilize",
                    "Third: Rebalance patch",
                    "Fourth: Re-run 3x verification",
                    "Fifth: Weld if stable",
                ],
                "priority": "GATES_FIRST_PATCH_SECOND_THEN_WELD",
            }
        else:
            self.results["recommendation"] = {
                "action": "needs_deeper_investigation",
                "steps": ["Run detailed gate-level tracing", "Check external dependencies"],
                "priority": "INVESTIGATE",
            }

    def _print_diagnosis(self) -> None:
        """Print diagnosis summary."""
        print("\n" + "=" * 70)
        print("DIAGNOSIS SUMMARY")
        print("=" * 70)
        print(f"Diagnosis: {self.results.get('diagnosis')}")
        print(f"Patch biased: {self.results.get('patch_biased')}")
        print(f"Gates jittering: {self.results.get('gates_jittering')}")
        print(f"Overall gate jitter: {self.results.get('gate_details', {}).get('overall_jitter')}")

        rec = self.results.get("recommendation", {})
        print(f"\nRecommendation: {rec.get('action')}")
        print(f"Priority: {rec.get('priority')}")
        print("\nSteps:")
        for i, step in enumerate(rec.get("steps", []), 1):
            print(f"  {i}. {step}")

    def _save_results(self) -> None:
        """Save autopsy results."""
        output_path = Path(f"projects/{self.project}/autopsy_canary_80_3x.json")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(self.results, f, indent=2)
        print(f"\n✓ Results saved to {output_path}")


def run_autopsy_canary_80_3x(project: str = "main", force: bool = False) -> dict:
    """Convenience function to run the autopsy."""
    autopsy = Canary80Autopsy(project)
    return autopsy.run_autopsy(force=force)


if __name__ == "__main__":
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "main"
    force = "--force" in sys.argv
    run_autopsy_canary_80_3x(project, force)
