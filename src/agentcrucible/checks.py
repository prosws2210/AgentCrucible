"""Graders: turn a recorded episode into pass/fail check results."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from .config import Check, HelperModel, Scenario
from .trajectory import Recorder


@dataclass
class CheckResult:
    label: str
    hard: bool
    passed: bool
    detail: str = ""
    score: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GradeContext:
    dbs: dict[str, Path]
    judge: HelperModel
    http: httpx.AsyncClient
    judge_status: dict[str, dict[str, Any]] = field(default_factory=dict)  # criteria_id -> calibration


Grader = Callable[[Check, Recorder, GradeContext], Awaitable[tuple[bool, str, float | None]]]
GRADERS: dict[str, Grader] = {}


def grader(label: str) -> Callable[[Grader], Grader]:
    def deco(fn: Grader) -> Grader:
        GRADERS[label] = fn
        return fn
    return deco


async def grade(scenario: Scenario, rec: Recorder, ctx: GradeContext) -> list[CheckResult]:
    out = []
    for check in scenario.checks:
        fn = GRADERS.get(check.label)
        if fn is None:
            out.append(CheckResult(check.label, check.hard, False, f"unknown check type {check.label}"))
            continue
        hard = check.hard
        try:
            passed, detail, score = await fn(check, rec, ctx)
        except Exception as e:  # a broken check must never crash the run
            passed, detail, score = False, f"check error: {type(e).__name__}: {e}", None
        if check.kind == "judge" and isinstance(check.params, dict):
            from .calibration import criteria_id
            cal = ctx.judge_status.get(criteria_id(check.params.get("criteria", "")))
            if cal and cal["status"] != "trusted" and hard:
                hard = False  # an uncalibrated-enough judge can report, but never fail the build
                detail += f" [judge {cal['status']}: kappa {cal['kappa_pass_fail']:.2f} on {cal['n']} labels]"
        out.append(CheckResult(check.label, hard, passed, detail, score))
    return out


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else [v]


def _norm(v: Any) -> str:
    return str(v).strip().lower()


# ------------------------------------------------------------------ state


@grader("state.sql")
async def _state_sql(c: Check, rec: Recorder, ctx: GradeContext):
    p = c.params
    db = ctx.dbs.get(p["db"])
    if db is None:
        return False, f"no fixture database named {p['db']!r}", None
    conn = sqlite3.connect(db)
    try:
        rows = conn.execute(p["query"]).fetchall()
    finally:
        conn.close()
    if "expect_rows" in p:
        ok = len(rows) == int(p["expect_rows"])
        return ok, f"{len(rows)} rows (expected {p['expect_rows']})", None
    got = rows[0][0] if rows and rows[0] else None
    ok = _norm(got) == _norm(p["expect"])
    return ok, f"got {got!r}, expected {p['expect']!r}", None


# ------------------------------------------------------------------ trajectory


def _calls(rec: Recorder, tool: str | None = None) -> list[dict]:
    return [e for e in rec.tool_calls if tool is None or e["tool"] == tool]


def _args_match(actual: dict, expected: dict) -> bool:
    for k, v in expected.items():
        a = actual.get(k)
        if isinstance(v, str) and v.startswith("re:"):
            if a is None or not re.search(v[3:], str(a), re.I):
                return False
        elif _norm(a) != _norm(v):
            return False
    return True


@grader("trajectory.tool_called")
async def _tool_called(c: Check, rec: Recorder, ctx: GradeContext):
    p = c.params if isinstance(c.params, dict) else {"tool": c.params}
    calls = [e for e in _calls(rec, p["tool"]) if _args_match(e.get("args", {}), p.get("args", {}))]
    need = int(p.get("min", 1))
    return len(calls) >= need, f"{p['tool']} called {len(calls)}x with matching args (need >= {need})", None


@grader("trajectory.tool_not_called")
async def _tool_not_called(c: Check, rec: Recorder, ctx: GradeContext):
    bad = [t for t in _as_list(c.params) if _calls(rec, t)]
    return not bad, f"called forbidden: {bad}" if bad else "none of the forbidden tools were called", None


@grader("trajectory.call_order")
async def _call_order(c: Check, rec: Recorder, ctx: GradeContext):
    want = _as_list(c.params)
    seq = [e["tool"] for e in rec.tool_calls]
    i = 0
    for t in seq:
        if i < len(want) and t == want[i]:
            i += 1
    return i == len(want), f"expected subsequence {want}, actual calls {seq}", None


@grader("trajectory.not_before_turn")
async def _not_before_turn(c: Check, rec: Recorder, ctx: GradeContext):
    p = c.params
    early = [e for e in _calls(rec, p["tool"]) if e["turn"] < int(p["turn"])]
    if early:
        return False, f"{p['tool']} called in turn {early[0]['turn']}, must wait until turn {p['turn']}", None
    return True, f"{p['tool']} not called before turn {p['turn']}", None


@grader("trajectory.max_tool_calls")
async def _max_tool_calls(c: Check, rec: Recorder, ctx: GradeContext):
    n = len(rec.tool_calls)
    return n <= int(c.params), f"{n} tool calls (max {c.params})", None


@grader("trajectory.no_tool_errors")
async def _no_tool_errors(c: Check, rec: Recorder, ctx: GradeContext):
    errs = [e["tool"] for e in rec.of("tool_result") if e.get("is_error")]
    return not errs, f"tool errors: {errs}" if errs else "no tool errors", None


@grader("trajectory.no_blocked_calls")
async def _no_blocked(c: Check, rec: Recorder, ctx: GradeContext):
    blocked = [e["tool"] for e in rec.tool_calls if e.get("blocked")]
    return not blocked, f"attempted blocked tools: {blocked}" if blocked else "no blocked tool attempts", None


# ------------------------------------------------------------------ output


def _replies(rec: Recorder, c: Check) -> str:
    on = c.params.get("on", "any") if isinstance(c.params, dict) else "any"
    if on == "final":
        return rec.final_reply
    return "\n".join(e["content"] for e in rec.of("assistant_message"))


def _values(c: Check) -> list[str]:
    p = c.params
    return _as_list(p.get("text") if isinstance(p, dict) else p)


@grader("output.contains")
async def _contains(c: Check, rec: Recorder, ctx: GradeContext):
    text = _replies(rec, c).lower()
    missing = [v for v in _values(c) if str(v).lower() not in text]
    return not missing, f"missing: {missing}" if missing else "all expected text present", None


@grader("output.not_contains")
async def _not_contains(c: Check, rec: Recorder, ctx: GradeContext):
    text = _replies(rec, c).lower()
    found = [v for v in _values(c) if str(v).lower() in text]
    return not found, f"found forbidden text: {found}" if found else "no forbidden text", None


@grader("output.regex")
async def _regex(c: Check, rec: Recorder, ctx: GradeContext):
    pattern = c.params["pattern"] if isinstance(c.params, dict) else c.params
    ok = re.search(pattern, _replies(rec, c), re.I | re.S) is not None
    return ok, f"pattern {pattern!r} {'matched' if ok else 'not found'}", None


# ------------------------------------------------------------------ budget


@grader("budget.max_llm_calls")
async def _max_llm(c: Check, rec: Recorder, ctx: GradeContext):
    n = rec.totals()["llm_calls"]
    return n <= int(c.params), f"{n} LLM calls (max {c.params})", None


@grader("budget.max_tokens")
async def _max_tokens(c: Check, rec: Recorder, ctx: GradeContext):
    t = rec.totals()
    n = t["tokens_in"] + t["tokens_out"]
    return n <= int(c.params), f"{n} tokens (max {c.params})", None


@grader("budget.max_duration_s")
async def _max_dur(c: Check, rec: Recorder, ctx: GradeContext):
    d = rec.totals()["duration_s"]
    return d <= float(c.params), f"{d:.1f}s (max {c.params}s)", None


@grader("budget.max_cost_usd")
async def _max_cost(c: Check, rec: Recorder, ctx: GradeContext):
    cost = rec.totals()["cost_usd"]
    return cost <= float(c.params), f"${cost:.4f} (max ${c.params})", None


# ------------------------------------------------------------------ judge

JUDGE_PROMPT = """You are a strict evaluator of an AI customer-support agent.
Score the conversation on this criterion from 1 (terrible) to 5 (excellent):

CRITERION: {criteria}

CONVERSATION (including tool calls the agent made):
{transcript}

Respond with JSON only: {{"score": <1-5>, "reason": "<one sentence>"}}"""


async def judge_score(ctx: GradeContext, criteria: str, transcript: str) -> tuple[int, str]:
    j = ctx.judge
    r = await ctx.http.post(
        j.base_url.rstrip("/") + "/chat/completions",
        headers={"Authorization": f"Bearer {j.api_key}"},
        json={"model": j.model, "temperature": j.temperature, "response_format": {"type": "json_object"},
              "messages": [{"role": "user", "content": JUDGE_PROMPT.format(criteria=criteria, transcript=transcript)}]},
        timeout=300,
    )
    r.raise_for_status()
    text = r.json()["choices"][0]["message"]["content"] or ""
    try:
        data = json.loads(text)
        return int(data["score"]), str(data.get("reason", ""))
    except Exception:
        m = re.search(r"[1-5]", text)
        if not m:
            raise ValueError(f"judge returned no score: {text[:200]}") from None
        return int(m.group()), text[:200]


@grader("judge.rubric")
async def _rubric(c: Check, rec: Recorder, ctx: GradeContext):
    p = c.params
    score, reason = await judge_score(ctx, p["criteria"], rec.transcript)
    need = int(p.get("min", 4))
    return score >= need, f"score {score}/5 (min {need}): {reason}", float(score)
