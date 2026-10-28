import asyncio
import sqlite3

import httpx

from agentcrucible.checks import GradeContext, grade
from agentcrucible.config import HelperModel, Scenario
from agentcrucible.trajectory import Recorder


def run(coro):
    return asyncio.run(coro)


def episode():
    rec = Recorder("e1", "s", 1)
    rec.turn = 1
    rec.add("user_message", content="refund please")
    rec.add("tool_call", server="shop", tool="find_customer", args={"email": "a@x.com"})
    rec.add("tool_result", server="shop", tool="find_customer", is_error=False, content="{}")
    rec.add("assistant_message", content="Shall I refund order A-1 for $10?")
    rec.turn = 2
    rec.add("user_message", content="yes")
    rec.add("tool_call", server="shop", tool="issue_refund", args={"order_id": "A-1"})
    rec.add("tool_result", server="shop", tool="issue_refund", is_error=False, content='{"ok": true}')
    rec.add("assistant_message", content="Done, refunded.")
    return rec


def scenario(checks):
    return Scenario.model_validate({"id": "s", "task": "t", "checks": checks})


def test_trajectory_and_output_checks(tmp_path):
    db = tmp_path / "shop.db"
    conn = sqlite3.connect(db)
    conn.executescript("CREATE TABLE refunds(order_id TEXT); INSERT INTO refunds VALUES ('A-1');")
    conn.close()
    sc = scenario([
        {"trajectory.call_order": ["find_customer", "issue_refund"]},
        {"trajectory.not_before_turn": {"tool": "issue_refund", "turn": 2}},
        {"trajectory.tool_not_called": "cancel_order"},
        {"trajectory.tool_called": {"tool": "find_customer", "args": {"email": r"re:@x\.com"}}},
        {"trajectory.max_tool_calls": 2},
        {"output.contains": "refunded"},
        {"output.not_contains": "password"},
        {"state.sql": {"db": "shop", "query": "SELECT count(*) FROM refunds", "expect": 1}},
        {"trajectory.not_before_turn": {"tool": "issue_refund", "turn": 3, "hard": False}},
    ])
    ctx = GradeContext(dbs={"shop": db}, judge=HelperModel(), http=httpx.AsyncClient())
    results = run(grade(sc, episode(), ctx))
    assert [r.passed for r in results] == [True] * 8 + [False]
    assert results[-1].hard is False


def test_unknown_check_fails_cleanly():
    sc = scenario([{"trajectory.does_not_exist": 1}])
    ctx = GradeContext(dbs={}, judge=HelperModel(), http=httpx.AsyncClient())
    (r,) = run(grade(sc, episode(), ctx))
    assert not r.passed and "unknown check" in r.detail
