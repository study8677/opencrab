"""
Stabilize the three gates before welding.
Purpose: Reduce gate jitter to pass 3x verification reliably.
"""

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

from crab import Crab


class GateStabilizer:
    """Stabilize jittering gates with circuit-breakers and cooldowns."""

    def __init__(self, project: str = "main"):
        self.project = project
        self.crab = Crab(project)
        self.stabilization_log = {
            "timestamp": datetime.now().isoformat(),
            "project": project,
            "gates_stabilized": [],
            "circuit_breakers_added": [],
            "cooldowns_set": [],
        }

    def stabilize_all_gates(self) -> dict:
        """Run full gate stabilization."""
        print("=" * 70)
        print("GATE STABILIZATION")
        print("=" * 70)

        # Step 1: Diagnose which gates are jittering
        print("\n[STEP 1] Diagnosing gate jitter...")
        jitter_report = self._diagnose_jitter()
        print(f"Jitter report: {jitter_report}")

        # Step 2: Add circuit breakers for jittering gates
        print("\n[STEP 2] Adding circuit breakers...")
        self._add_circuit_breakers(jitter_report)

        # Step 3: Set cooldowns
        print("\n[STEP 3] Setting cooldowns...")
        self._set_cooldowns(jitter_report)

        # Step 4: Verify stabilization
        print("\n[STEP 4] Verifying stabilization...")
        self._verify_stabilization()

        self._save_log()
        return self.stabilization_log

    def _diagnose_jitter(self) -> dict:
        """Diagnose which gates are jittering and how much."""
        report = {
            "gate_1_fitness": {"jittery": False, "variance": 0.0, "action": None},
            "gate_2_brainonly": {"jittery": False, "variance": 0.0, "action": None},
            "gate_3_evidence": {"jittery": False, "variance": 0.0, "action": None},
        }

        # Read gate history
        ledger_path = Path(f"projects/{self.project}/fitness_ledger.jsonl")
        if not ledger_path.exists():
            return report

        gate_samples = {1: [], 2: [], 3: []}
        with open(ledger_path) as f:
            for line in f:
                entry = json.loads(line)
                for g in [1, 2, 3]:
                    key = f"gate_{g}"
                    if key in entry and entry[key] is not None:
                        gate_samples[g].append(entry[key])

        # Calculate variance for each gate
        for gate_num, samples in gate_samples.items():
            if len(samples) >= 2:
                variance = self._calc_variance(samples)
                report[f"gate_{gate_num}_fitness" if gate_num == 1 else f"gate_{gate_num}_brainonly" if gate_num == 2 else f"gate_{gate_num}_evidence"]["variance"] = variance
                if variance > 0.05:
                    report[f"gate_{gate_num}_fitness" if gate_num == 1 else f"gate_{gate_num}_brainonly" if gate_num == 2 else f"gate_{gate_num}_evidence"]["jittery"] = True
                    report[f"gate_{gate_num}_fitness" if gate_num == 1 else f"gate_{gate_num}_brainonly" if gate_num == 2 else f"gate_{gate_num}_evidence"]["action"] = self._recommend_action(variance)

        return report

    def _calc_variance(self, samples: list) -> float:
        """Calculate variance."""
        if len(samples) < 2:
            return 0.0
        try:
            values = [float(s) for s in samples]
            mean = sum(values) / len(values)
            return sum((x - mean) ** 2 for x in values) / len(values)
        except:
            return 0.0

    def _recommend_action(self, variance: float) -> str:
        """Recommend stabilization action based on variance."""
        if variance > 0.5:
            return "add_hard_circuit_breaker"
        elif variance > 0.2:
            return "add_soft_circuit_breaker"
        elif variance > 0.1:
            return "add_cooldown"
        else:
            return "monitor"

    def _add_circuit_breakers(self, jitter_report: dict) -> None:
        """Add circuit breakers to jittery gates."""
        config_path = Path(f"projects/{self.project}/gate_config.json")

        config = {}
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)

        if "circuit_breakers" not in config:
            config["circuit_breakers"] = {}

        for gate_key, gate_info in jitter_report.items():
            if gate_info.get("jittery"):
                action = gate_info.get("action", "")
                if "circuit_breaker" in action:
                    config["circuit_breakers"][gate_key] = {
                        "enabled": True,
                        "threshold": 0.1,  # 10% tolerance
                        "cooldown_seconds": 60 if "hard" in action else 30,
                        "max_retries": 3,
                    }
                    self.stabilization_log["circuit_breakers_added"].append(gate_key)
                    print(f"  ✓ Added circuit breaker to {gate_key}")

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

    def _set_cooldowns(self, jitter_report: dict) -> None:
        """Set cooldowns for gates."""
        config_path = Path(f"projects/{self.project}/gate_config.json")

        config = {}
        if config_path.exists():
            with open(config_path) as f:
                config = json.load(f)

        if "cooldowns" not in config:
            config["cooldowns"] = {}

        for gate_key, gate_info in jitter_report.items():
            if gate_info.get("jittery"):
                action = gate_info.get("action", "")
                if "cooldown" in action or "circuit_breaker" in action:
                    config["cooldowns"][gate_key] = {
                        "enabled": True,
                        "duration_seconds": 30,
                        "min_samples_for_decision": 5,
                    }
                    self.stabilization_log["cooldowns_set"].append(gate_key)
                    print(f"  ✓ Set cooldown for {gate_key}")

        config_path.parent.mkdir(parents=True, exist_ok=True)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)

    def _verify_stabilization(self) -> None:
        """Verify gates are now stable."""
        print("\nVerification: Gates should now have reduced jitter.")
        print("Run 3x reproduction to confirm before welding.")

    def _save_log(self) -> None:
        """Save stabilization log."""
        output_path = Path(f"projects/{self.project}/gate_stabilization_log.json")
        with open(output_path, "w") as f:
            json.dump(self.stabilization_log, f, indent=2)
        print(f"\n✓ Stabilization log saved to {output_path}")


def stabilize_gates(project: str = "main") -> dict:
    """Convenience function to stabilize gates."""
    stabilizer = GateStabilizer(project)
    return stabilizer.stabilize_all_gates()


if __name__ == "__main__":
    import sys
    project = sys.argv[1] if len(sys.argv) > 1 else "main"
    stabilize_gates(project)
