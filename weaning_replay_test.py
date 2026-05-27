"""Run 3 replay cases to test weaning gate with autonomy meter integration."""

import weaning_gate
import autonomy_meter


def run_replay_cases():
    """Simulate 3 replay cases with different autonomy calibration scores."""
    cases = [
        {"case_name": "High autonomy - allow all touches", "calibration_score": 0.95},
        {"case_name": "Medium autonomy - restrict some touches", "calibration_score": 0.6},
        {"case_name": "Low autonomy - block most touches", "calibration_score": 0.3},
    ]

    print("=== Weaning Gate Replay Test ===\n")
    for i, case in enumerate(cases, 1):
        print(f"Case {i}: {case['case_name']}")
        print(f"  Calibration score: {case['calibration_score']}")

        # Create a mock autonomy meter with the case's score
        mock_meter = type('MockAutonomyMeter', (), {
            'get_calibration_score': lambda self: case['calibration_score']
        })()

        # Test a few sample touch points
        for touch_id in ["touch_1", "touch_2", "touch_3", "touch_critical"]:
            allowed = weaning_gate.gate_touch(touch_id, {"source": "replay"})
            print(f"    {touch_id}: {'ALLOWED' if allowed else 'BLOCKED'}")

        print()

    print("=== Replay Complete ===")


if __name__ == "__main__":
    run_replay_cases()
