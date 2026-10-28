import math

from agentcrucible.calibration import cohen_kappa, quadratic_weighted_kappa, status_for, summarize


def test_kappa_perfect_and_chance():
    assert cohen_kappa([1, 0, 1, 0], [1, 0, 1, 0]) == 1.0
    # judge always says pass: agreement equals chance -> kappa 0
    assert math.isclose(cohen_kappa([1, 0, 1, 0], [1, 1, 1, 1]), 0.0)


def test_kappa_textbook_value():
    # 2x2 table [[20, 5], [10, 15]] -> po = .70, pe = .50, kappa = .40
    a = [1] * 25 + [0] * 25
    b = [1] * 20 + [0] * 5 + [1] * 10 + [0] * 15
    assert math.isclose(cohen_kappa(a, b), 0.4, abs_tol=1e-9)


def test_quadratic_kappa_penalizes_distance():
    near = quadratic_weighted_kappa([1, 2, 3, 4, 5], [2, 2, 3, 4, 5])
    far = quadratic_weighted_kappa([1, 2, 3, 4, 5], [5, 2, 3, 4, 1])
    assert near > far


def test_status_thresholds_and_summary():
    assert status_for(0.75) == "trusted" and status_for(0.5) == "advisory" and status_for(0.1) == "disabled"
    pairs = [{"episode_id": str(i), "human": h, "judge": j, "reason": ""} for i, (h, j) in
             enumerate([(5, 5), (2, 4), (4, 4), (1, 2), (5, 3)])]
    s = summarize("be nice", 4, pairs, "m")
    assert s["n"] == 5 and sum(s["confusion"].values()) == 5
