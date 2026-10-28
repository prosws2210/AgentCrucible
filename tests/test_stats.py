import math

from agentcrucible.stats import benjamini_hochberg, compare_runs, gate, pass_at_k, pass_pow_k, summarize_run


def make_run(run_id, results):
    """results: {scenario_id: [True, False, ...]}"""
    eps = []
    for sid, outcomes in results.items():
        for i, ok in enumerate(outcomes, 1):
            eps.append({"episode_id": f"{sid}-{i}", "scenario_id": sid, "attempt": i, "passed": ok, "error": None,
                        "checks": [], "trajectory": "", "totals": {"duration_s": 1.0, "tokens_in": 10, "tokens_out": 5,
                                                                     "cost_usd": 0.0}})
    run = {"run_id": run_id, "episodes": eps}
    run["summary"] = summarize_run(run)
    return run


def test_pass_at_k_and_pow_k():
    assert pass_at_k(5, 5, 5) == 1.0
    assert pass_pow_k(5, 5, 5) == 1.0
    assert pass_pow_k(5, 4, 5) == 0.0           # one failure in 5 -> not all 5 pass
    assert math.isclose(pass_at_k(5, 1, 1), 0.2)
    assert math.isclose(pass_pow_k(10, 8, 2), 28 / 45)
    assert math.isnan(pass_at_k(3, 1, 5))


def test_bh_is_monotone_and_bounded():
    adj = benjamini_hochberg([0.01, 0.04, 0.03, 0.5])
    assert all(0 <= a <= 1 for a in adj)
    assert adj[0] <= adj[2] <= adj[1] <= adj[3]


def test_detects_clear_regression():
    base = make_run("b", {"s1": [True] * 8, "s2": [True] * 8})
    cand = make_run("c", {"s1": [False] * 8, "s2": [True] * 8})
    cmp = compare_runs(base, cand)
    verdicts = {r["scenario_id"]: r["verdict"] for r in cmp["scenarios"]}
    assert verdicts == {"s1": "regressed", "s2": "unchanged"}
    ok, reasons = gate(cmp, cand, ["regressed"])
    assert not ok and reasons


def test_noise_is_not_flagged():
    base = make_run("b", {f"s{i}": [True, True, False] for i in range(10)})
    cand = make_run("c", {f"s{i}": [True, False, True] for i in range(10)})
    cmp = compare_runs(base, cand)
    assert cmp["counts"]["regressed"] == 0
    assert cmp["overall"]["verdict"] == "unchanged"


def test_small_k_large_drop_is_inconclusive_with_runs_needed():
    base = make_run("b", {f"s{i}": [True] * 3 for i in range(10)})
    cand = make_run("c", {**{f"s{i}": [True] * 3 for i in range(9)}, "s9": [False] * 3})
    row = next(r for r in compare_runs(base, cand)["scenarios"] if r["scenario_id"] == "s9")
    assert row["verdict"] == "inconclusive"
    assert row["runs_needed"] and row["runs_needed"] > 3
