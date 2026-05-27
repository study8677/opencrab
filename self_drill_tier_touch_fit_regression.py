"""Regression checks for the brain-only tiergate/touchgraph/patchfitroom drill."""

from __future__ import annotations

from self_drill_tier_touch_fit import (
    accepts_controlled_two_file,
    build_drill_plan,
    tiergate_classify,
    touchgraph_edges,
)


def test_tiergate_marks_two_files_as_controlled() -> None:
    assert tiergate_classify(["tiergate.py", "touchgraph.py"]) == "controlled-two-file"


def test_touchgraph_links_adjacent_files() -> None:
    assert touchgraph_edges(["tiergate.py", "touchgraph.py"]) == (
        ("tiergate.py", "touchgraph.py"),
    )


def test_full_drill_plan_passes_patchfitroom_constraints() -> None:
    plan = build_drill_plan(
        "advance from single-point edit to controlled two-file hand edit",
        ["tiergate.py", "touchgraph.py"],
    )

    assert plan.tier == "controlled-two-file"
    assert plan.touch_edges == (("tiergate.py", "touchgraph.py"),)
    assert "py-compile" in plan.fit_checks
    assert "import-crab" in plan.fit_checks
    assert accepts_controlled_two_file(plan)


def run_regression() -> bool:
    test_tiergate_marks_two_files_as_controlled()
    test_touchgraph_links_adjacent_files()
    test_full_drill_plan_passes_patchfitroom_constraints()
    return True


if __name__ == "__main__":
    run_regression()
    print("self_drill_tier_touch_fit_regression: ok")
