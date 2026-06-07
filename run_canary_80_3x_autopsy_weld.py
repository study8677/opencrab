"""
CLI entry point for canary 80 3x autopsy-weld pipeline.
Usage: python run_canary_80_3x_autopsy_weld.py [project]
"""

import sys
import json
from pathlib import Path

from canary_80_3x_autopsy_weld import run_canary_80_3x_autopsy_weld


def main():
    project = sys.argv[1] if len(sys.argv) > 1 else "main"

    print(f"Running canary 80 3x autopsy-weld for project: {project}")

    results = run_canary_80_3x_autopsy_weld(project)

    # Save results
    output_path = Path(f"projects/{project}/canary_80_3x_pipeline_results.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n✓ Results saved to {output_path}")

    return 0 if results.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
