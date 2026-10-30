"""Statistics: reliability metrics and regression detection that doesn't cry wolf.

Definitions (n episodes of a scenario, c of them passed):
    pass@1   = c / n                            average success rate
    pass@k   = 1 - C(n-c, k) / C(n, k)          P(at least one of k tries succeeds)   -> capability
    pass^k   = C(c, k) / C(n, k)                P(all k tries succeed)                -> reliability
Both estimators are unbiased (Chen et al. 2021 for pass@k; pass^k is the complementary form).

Comparing two runs:
    per scenario  Fisher's exact test on the 2x2 pass/fail table, then Benjamini-Hochberg across
                  scenarios so a 100-scenario suite doesn't produce false alarms by chance.
    overall       hierarchical bootstrap (resample scenarios, then episodes within each) of the
                  difference in mean pass rate -> 95% confidence interval.
"""

from __future__ import annotations

from collections import defaultdict
from math import comb
from typing import Any

import numpy as np
from scipy.stats import fisher_exact

RNG_SEED = 1234


def pass_at_k(n: int, c: int, k: int) -> float:
    if k > n or n == 0:
        return float("nan")
    if n - c < k:
        return 1.0
    return 1.0 - comb(n - c, k) / comb(n, k)


def pass_pow_k(n: int, c: int, k: int) -> float:
    if k > n or n == 0:
        return float("nan")
    return comb(c, k) / comb(n, k)


def _pct(values: list[float], q: float) -> float:
    return float(np.percentile(values, q)) if values else 0.0


def _by_scenario(run: dict[str, Any]) -> dict[str, list[bool]]:
    out: dict[str, list[bool]] = defaultdict(list)
    for e in run["episodes"]:
        out[e["scenario_id"]].append(bool(e["passed"]))
    return dict(out)


def bootstrap_mean_ci(groups: list[list[bool]], b: int = 4000, seed: int = RNG_SEED) -> tuple[float, float]:
    """95% CI of the macro-average pass rate via hierarchical bootstrap."""
    if not groups:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    arrs = [np.array(g, dtype=float) for g in groups]
    m = len(arrs)
    stats = np.empty(b)
    for i in range(b):
        idx = rng.integers(0, m, m)
        stats[i] = np.mean([rng.choice(arrs[j], len(arrs[j])).mean() for j in idx])
    return float(np.percentile(stats, 2.5)), float(np.percentile(stats, 97.5))


def summarize_run(run: dict[str, Any]) -> dict[str, Any]:
    by = _by_scenario(run)
    scen = {}
    for sid, res in by.items():
        n, c = len(res), sum(res)
        scen[sid] = {"n": n, "passed": c, "pass_rate": c / n, "pass_pow_k": pass_pow_k(n, c, n),
                     "flaky": 0 < c < n}
    k = min((v["n"] for v in scen.values()), default=0)
    eps = run["episodes"]
    durations = [e["totals"]["duration_s"] for e in eps]
    ci = bootstrap_mean_ci(list(by.values()))
    return {
        "scenarios": scen,
        "n_scenarios": len(scen),
        "n_episodes": len(eps),
        "k": k,
        "pass_at_1": float(np.mean([v["pass_rate"] for v in scen.values()])) if scen else 0.0,
        "pass_at_1_ci": ci,
        "pass_pow_k": float(np.mean([pass_pow_k(len(r), sum(r), k) for r in by.values()])) if k else 0.0,
        "pass_at_k": float(np.mean([pass_at_k(len(r), sum(r), k) for r in by.values()])) if k else 0.0,
        "flaky_scenarios": sorted(s for s, v in scen.items() if v["flaky"]),
        "errors": sum(1 for e in eps if e.get("error")),
        "tokens_per_episode": float(np.mean([e["totals"]["tokens_in"] + e["totals"]["tokens_out"] for e in eps])) if eps else 0.0,
        "cost_usd": round(sum(e["totals"]["cost_usd"] for e in eps), 4),
        "duration_p50_s": _pct(durations, 50),
        "duration_p95_s": _pct(durations, 95),
    }


def benjamini_hochberg(pvals: list[float]) -> list[float]:
    m = len(pvals)
    if m == 0:
        return []
    order = np.argsort(pvals)
    adj = np.empty(m)
    prev = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        prev = min(prev, pvals[i] * m / rank)
        adj[i] = prev
    return adj.tolist()


def runs_needed(pb: float, pc: float, alpha: float, max_k: int = 60) -> int | None:
    """Smallest k per side at which the observed rates would be significant (Bonferroni-ish bound)."""
    if pb == pc:
        return None
    for k in range(2, max_k + 1):
        a, b = round(pb * k), round(pc * k)
        if a == b:
            continue
        _, p = fisher_exact([[a, k - a], [b, k - b]])
        if p < alpha:
            return k
    return None


def compare_runs(base: dict[str, Any], cand: dict[str, Any], alpha: float = 0.05,
                 b: int = 4000, seed: int = RNG_SEED) -> dict[str, Any]:
    bb, cc = _by_scenario(base), _by_scenario(cand)
    common = sorted(set(bb) & set(cc))
    rows, pvals = [], []
    for sid in common:
        nb, kb = len(bb[sid]), sum(bb[sid])
        nc, kc = len(cc[sid]), sum(cc[sid])
        _, p = fisher_exact([[kb, nb - kb], [kc, nc - kc]])
        pvals.append(float(p))
        rows.append({"scenario_id": sid, "base_n": nb, "base_passed": kb, "cand_n": nc, "cand_passed": kc,
                     "base_rate": kb / nb, "cand_rate": kc / nc, "delta": kc / nc - kb / nb, "p": float(p)})
    for row, padj in zip(rows, benjamini_hochberg(pvals), strict=False):
        row["p_adj"] = padj
        d = row["delta"]
        if padj < alpha and d < 0:
            row["verdict"] = "regressed"
        elif padj < alpha and d > 0:
            row["verdict"] = "improved"
        elif abs(d) >= 0.2:
            row["verdict"] = "inconclusive"
            row["runs_needed"] = runs_needed(row["base_rate"], row["cand_rate"], alpha / max(1, len(rows)))
        else:
            row["verdict"] = "unchanged"

    # hierarchical paired bootstrap of the overall difference
    rng = np.random.default_rng(seed)
    if common:
        A = [np.array(bb[s], dtype=float) for s in common]
        C = [np.array(cc[s], dtype=float) for s in common]
        m = len(common)
        diffs = np.empty(b)
        for i in range(b):
            idx = rng.integers(0, m, m)
            diffs[i] = np.mean([rng.choice(C[j], len(C[j])).mean() - rng.choice(A[j], len(A[j])).mean() for j in idx])
        lo, hi = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
        delta = float(np.mean([c.mean() for c in C]) - np.mean([a.mean() for a in A]))
    else:
        lo = hi = delta = float("nan")

    if common and hi < 0:
        overall = "regressed"
    elif common and lo > 0:
        overall = "improved"
    else:
        overall = "unchanged"
    # a run whose episodes all crashed measured nothing: no difference against it means nothing either
    crashed = [name for name, r in (("baseline", base), ("this run", cand))
               if r["summary"].get("n_episodes") and (r["summary"].get("errors") or 0) >= r["summary"]["n_episodes"]]
    if crashed:
        overall = "inconclusive"
    counts = {v: sum(1 for r in rows if r["verdict"] == v) for v in ("regressed", "improved", "inconclusive", "unchanged")}
    return {
        "base_run": base["run_id"], "cand_run": cand["run_id"], "alpha": alpha,
        "overall": {"verdict": overall, "delta": delta, "ci": [lo, hi],
                    "base": base["summary"], "cand": cand["summary"],
                    **({"note": f"Every episode of {' and '.join(crashed)} errored, so the comparison can't tell anything."}
                       if crashed else {})},
        "counts": counts,
        "scenarios": sorted(rows, key=lambda r: ({"regressed": 0, "inconclusive": 1, "improved": 2}.get(r["verdict"], 3), r["delta"])),
        "only_in_base": sorted(set(bb) - set(cc)),
        "only_in_cand": sorted(set(cc) - set(bb)),
    }


def gate(comparison: dict[str, Any] | None, run: dict[str, Any], fail_on: list[str],
         max_error_rate: float = 0.2) -> tuple[bool, list[str]]:
    """Return (ok, reasons) for CI. A run whose episodes mostly crashed measured nothing, so it never passes."""
    reasons = []
    s = run["summary"]
    errors, n = s.get("errors") or 0, s.get("n_episodes") or 0
    if n and (errors >= n or errors / n > max_error_rate):
        reasons.append(f"{errors} of {n} episodes errored before they could be graded" + (": nothing ran" if errors >= n else ""))
    if "any_failure" in fail_on and run["summary"]["pass_at_1"] < 1.0:
        reasons.append("some episodes failed")
    if comparison:
        if "regressed" in fail_on:
            n = comparison["counts"]["regressed"]
            if n:
                reasons.append(f"{n} scenario(s) significantly regressed")
            if comparison["overall"]["verdict"] == "regressed":
                reasons.append("overall pass rate significantly regressed")
        if "inconclusive" in fail_on and comparison["counts"]["inconclusive"]:
            reasons.append(f"{comparison['counts']['inconclusive']} scenario(s) inconclusive")
    return (not reasons, reasons)
