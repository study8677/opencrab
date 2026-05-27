import unittest

from brainonly_graduation_sample import (
    brainonly_graduation_report,
    is_brainonly_graduation_sample,
)


class BrainonlyGraduationSampleTest(unittest.TestCase):
    def test_accepts_complete_positive_brainonly_flow(self):
        events = [
            {"phase": "generate", "tool": "brain", "benefit": 0.2},
            {"phase": "fit", "tool": "brain", "benefit": 0.1},
            {"phase": "validate", "tool": "brain", "benefit": 0.1},
            {"phase": "backfill", "tool": "brain", "benefit": 0.1},
        ]

        report = brainonly_graduation_report(events)

        self.assertTrue(report["passed"])
        self.assertEqual(report["missing_phases"], ())
        self.assertEqual(report["forbidden_tools"], ())
        self.assertAlmostEqual(report["benefit_total"], 0.5)
        self.assertTrue(is_brainonly_graduation_sample(events))

    def test_rejects_forbidden_tool_even_when_otherwise_complete(self):
        events = [
            {"phase": "generate", "tool": "brain", "benefit": 1},
            {"phase": "fit", "tool": "claude", "benefit": 1},
            {"phase": "validate", "tool": "brain", "benefit": 1},
            {"phase": "backfill", "tool": "brain", "benefit": 1},
        ]

        report = brainonly_graduation_report(events)

        self.assertFalse(report["passed"])
        self.assertEqual(report["forbidden_tools"], ("claude",))

    def test_rejects_missing_phase_or_non_positive_benefit(self):
        missing = [
            {"phase": "generate", "tool": "brain", "benefit": 1},
            {"phase": "fit", "tool": "brain", "benefit": 1},
            {"phase": "validate", "tool": "brain", "benefit": 1},
        ]
        no_gain = [
            {"phase": "generate", "tool": "brain", "benefit": 0},
            {"phase": "fit", "tool": "brain", "benefit": 0},
            {"phase": "validate", "tool": "brain", "benefit": 0},
            {"phase": "backfill", "tool": "brain", "benefit": 0},
        ]

        self.assertFalse(brainonly_graduation_report(missing)["passed"])
        self.assertEqual(brainonly_graduation_report(missing)["missing_phases"], ("backfill",))
        self.assertFalse(is_brainonly_graduation_sample(no_gain))


if __name__ == "__main__":
    unittest.main()
