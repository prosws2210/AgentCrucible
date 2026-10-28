"""Judge calibration: measure how well an LLM judge agrees with human labels.

Workflow
    crucible label   <run> --criteria "..."   humans score episodes 1-5 (stored as JSONL)
    crucible calibrate     --criteria "..."   judge scores the same episodes; Cohen's kappa
                                                 decides whether the judge may fail CI:
        trusted   kappa >= 0.6   judge.rubric checks keep their hard/soft setting
        advisory  0.4 <= k < 0.6 judge.rubric checks are forced to soft (reported only)
        disabled  kappa < 0.4    same, and flagged in the report
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

TRUSTED, ADVISORY = 0.6, 0.4


def criteria_id(criteria: str) -> str:
    return hashlib.sha256(" ".join(criteria.split()).lower().encode()).hexdigest()[:10]


def labels_path(root: Path, criteria: str) -> Path:
    return root / ".crucible" / "labels" / f"{criteria_id(criteria)}.jsonl"


def calibration_path(root: Path, criteria: str) -> Path:
    return root / ".crucible" / "judges" / f"{criteria_id(criteria)}.json"


def load_labels(root: Path, criteria: str) -> dict[str, dict[str, Any]]:
    f = labels_path(root, criteria)
    out: dict[str, dict[str, Any]] = {}
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                out[row["episode_id"]] = row  # last label wins
    return out


def save_label(root: Path, criteria: str, row: dict[str, Any]) -> None:
    f = labels_path(root, criteria)
    f.parent.mkdir(parents=True, exist_ok=True)
    with f.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row) + "\n")


def cohen_kappa(a: list[int], b: list[int]) -> float:
    """Unweighted Cohen's kappa for two raters over the same items."""
    cats = sorted(set(a) | set(b))
    if len(a) == 0:
        return float("nan")
    idx = {c: i for i, c in enumerate(cats)}
    m = np.zeros((len(cats), len(cats)))
    for x, y in zip(a, b, strict=False):
        m[idx[x], idx[y]] += 1
    n = m.sum()
    po = np.trace(m) / n
    pe = float((m.sum(0) * m.sum(1)).sum()) / n**2
    return 1.0 if pe == 1 else float((po - pe) / (1 - pe))


def quadratic_weighted_kappa(a: list[int], b: list[int], lo: int = 1, hi: int = 5) -> float:
    k = hi - lo + 1
    if not a:
        return float("nan")
    o = np.zeros((k, k))
    for x, y in zip(a, b, strict=False):
        o[x - lo, y - lo] += 1
    w = np.array([[(i - j) ** 2 / (k - 1) ** 2 for j in range(k)] for i in range(k)])
    e = np.outer(o.sum(1), o.sum(0)) / o.sum()
    denom = (w * e).sum()
    return 1.0 if denom == 0 else float(1 - (w * o).sum() / denom)


def status_for(kappa: float) -> str:
    if kappa != kappa:
        return "uncalibrated"
    return "trusted" if kappa >= TRUSTED else "advisory" if kappa >= ADVISORY else "disabled"


def summarize(criteria: str, threshold: int, pairs: list[dict[str, Any]], judge_model: str) -> dict[str, Any]:
    human = [p["human"] for p in pairs]
    judge = [p["judge"] for p in pairs]
    hb = [int(h >= threshold) for h in human]
    jb = [int(j >= threshold) for j in judge]
    kappa = cohen_kappa(hb, jb)
    tp = sum(1 for h, j in zip(hb, jb, strict=False) if h and j)
    fp = sum(1 for h, j in zip(hb, jb, strict=False) if not h and j)
    fn = sum(1 for h, j in zip(hb, jb, strict=False) if h and not j)
    tn = sum(1 for h, j in zip(hb, jb, strict=False) if not h and not j)
    disagreements = sorted(pairs, key=lambda p: -abs(p["human"] - p["judge"]))[:10]
    return {
        "criteria": criteria, "criteria_id": criteria_id(criteria), "judge_model": judge_model,
        "threshold": threshold, "n": len(pairs),
        "kappa_pass_fail": kappa, "kappa_quadratic_1to5": quadratic_weighted_kappa(human, judge),
        "agreement": (tp + tn) / len(pairs) if pairs else float("nan"),
        "confusion": {"judge_pass_human_pass": tp, "judge_pass_human_fail": fp,
                      "judge_fail_human_pass": fn, "judge_fail_human_fail": tn},
        "status": status_for(kappa),
        "disagreements": [{k: p[k] for k in ("episode_id", "human", "judge", "reason")} for p in disagreements
                          if p["human"] != p["judge"]],
        "pairs": pairs,
    }


def load_statuses(root: Path) -> dict[str, dict[str, Any]]:
    out = {}
    for f in (root / ".crucible" / "judges").glob("*.json"):
        data = json.loads(f.read_text(encoding="utf-8"))
        out[data["criteria_id"]] = data
    return out
