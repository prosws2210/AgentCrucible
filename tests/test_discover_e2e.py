"""Codebase import end to end on examples/import-demo, with a scripted model (no download):

discover (static analysis) -> plan (adapters, fixtures, mocks, drafts) -> apply (write + validate) -> smoke run
-> discovery vs reality. Checks that in-process tools are traced through the generated adapter, the app's own
DATABASE_URL and PAYMENTS_API_BASE settings are pointed at the episode's fixture and HTTP mock, and destructive tools
are mocked by default.
"""

import json
import re
import shutil
import threading
import time
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, Request

from agentcrucible.discover import apply, build_plan, discover
from agentcrucible.gateway import free_port
from agentcrucible.trajectory import load_events

DEMO = Path(__file__).resolve().parent.parent / "examples" / "import-demo"
DESTRUCTIVE = {"issue_refund", "cancel_order"}


def scripted_model() -> FastAPI:
    """A small, well-behaved 'model': picks the best-matching tool, asks before destructive actions."""
    app = FastAPI()

    def reply(body: dict, msg: dict, finish: str = "stop") -> dict:
        return {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
                "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", **msg}}]}

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        msgs = body["messages"]
        tools = body.get("tools") or []
        if not tools and '"score"' in msgs[-1]["content"]:  # the judge
            return reply(body, {"content": json.dumps({"score": 5, "reason": "gives the expected information"})})
        if not tools:  # the user simulator
            return reply(body, {"content": "Yes, please go ahead."})
        users = [m for m in msgs if m["role"] == "user"]
        last = users[-1]["content"]
        if msgs[-1]["role"] == "tool":
            return reply(body, {"content": f"Done: {msgs[-1]['content'][:200]}"})
        if "everyone" in last or "all records" in last:
            return reply(body, {"content": "I can't do that for everyone without checking each request."})
        words = set(re.findall(r"[a-z]+", " ".join(u["content"] for u in users).lower()))

        def score(t: dict) -> int:
            f = t["function"]
            return len(words & set(re.findall(r"[a-z]+", (f["name"].replace("_", " ") + " " + f.get("description", "")).lower())))
        best = max(tools, key=score)
        name = best["function"]["name"]
        if score(best) == 0:  # nothing matches by name: a knowledge search is the sensible first step
            best = next((t for t in tools if "search" in t["function"]["name"]), None)
            if best is None:
                return reply(body, {"content": "Happy to help: I can look up orders, refunds and shipping information."})
            name = best["function"]["name"]
        if name in DESTRUCTIVE and len(users) < 2:
            return reply(body, {"content": "Before I do that, can you confirm?"})
        details = dict(re.findall(r"(\w+): ([^,.]+(?:\.\d+)?)", " ".join(u["content"] for u in users)))
        props = best["function"]["parameters"].get("properties", {})
        args = {p: (int(details[p]) if props[p].get("type") == "integer" and details.get(p, "").isdigit() else details.get(p, "A-1001"))
                for p in props}
        if "customer_id" in args and not isinstance(args["customer_id"], int):
            args["customer_id"] = 1
        if "query" in args:
            args["query"] = "shipping" if "shipping" in last.lower() else last
        return reply(body, {"content": "", "tool_calls": [{"id": f"c{len(msgs)}", "type": "function",
                                                            "function": {"name": name, "arguments": json.dumps(args)}}]}, "tool_calls")

    return app


def start(app):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    return server, th, port


def test_discover_finds_the_demo_agent(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(DEMO, repo)
    d = discover(repo)
    included = [a for a in d.agents if a.include]
    assert [a.id for a in included] == ["run-agent"]
    ag = included[0]
    assert ag.framework == "raw-openai" and ag.entrypoint.kind == "code"
    assert (ag.entrypoint.module, ag.entrypoint.object) == ("acme.agent", "run_agent")
    assert set(ag.tools) == {"find_customer", "list_orders", "issue_refund", "cancel_order", "search_help_center"}
    assert ag.system_prompt.file and ag.system_prompt.file.endswith("support.md") or ag.system_prompt.text
    effects = {t.name: set(t.effects) for t in d.tools}
    assert effects["issue_refund"] >= {"destructive", "writes data", "external call"}
    assert effects["cancel_order"] >= {"destructive"}
    assert effects["find_customer"] == {"read-only"}
    assert {s.name for s in d.mcp_servers} == {"knowledge_base"}
    assert d.datastores and d.datastores[0].url_env == "DATABASE_URL"
    assert set(d.datastores[0].tables) >= {"customers", "orders", "refunds"}
    assert any(api.base_url_env == "PAYMENTS_API_BASE" and "POST /v1/refunds" in api.paths for api in d.external_apis)
    assert {c["input"] for c in d.test_cases} == {"How long does standard shipping take?", "Can I return something I bought last week?"}
    assert "OPENAI_MODEL" in d.env_vars
    # every fact has evidence pointing at a real line
    for f in d.facts.values():
        assert f.evidence and (repo / f.evidence[0].file).exists() and f.evidence[0].line >= 1


def test_apply_and_smoke_run(tmp_path):
    repo = tmp_path / "repo"
    shutil.copytree(DEMO, repo)
    d = discover(repo)
    build_plan(d, repo)
    plan = d.plans[0]
    assert plan.strategy == "code" and plan.env_map == {"DATABASE_URL": "db:app", "PAYMENTS_API_BASE": "http:payments"}
    assert "acme.tools" in plan.adapter_code and "function.serve(run_agent)" in plan.adapter_code
    server, th, port = start(scripted_model())
    try:
        result = apply(d, repo, model="fake-model", upstream=f"http://127.0.0.1:{port}/v1")
    finally:
        server.should_exit = True
        th.join(5)
    out = repo / "agent-tests"
    assert (out / "crucible.yaml").exists() and (out / "discovery.json").exists()
    assert result["validate"]["agents"] == ["run-agent"]
    assert {c["id"]: c["ok"] for c in result["connection"]} == {"model": True, "mcp:knowledge_base": True, "agent:run-agent": True}
    budgets = yaml.safe_load((out / "scenarios" / "run-agent" / "run-agent-list-orders-uses.yaml").read_text(encoding="utf-8"))
    assert any("budget.max_tokens" in c for c in budgets["checks"])  # set from what the smoke run used
    rep = result["reality"]
    assert rep["errors"] == 0, rep["findings"]
    assert rep["passed"] == rep["episodes"], [s for s in rep["scenarios"] if not s["passed"]]
    seen = rep["observed_tools"]["run-agent"]
    assert {"find_customer", "list_orders", "search_help_center", "issue_refund"} <= set(seen)

    run_dir = out / ".crucible" / "runs" / rep["run_id"]
    run = json.loads((run_dir / "run.json").read_text())
    by_id = {ep["scenario_id"]: ep for ep in run["episodes"]}
    # the destructive tool is mocked by default, asked for confirmation, and traced through the adapter
    ep = by_id["run-agent-issue-refund-asks-first"]
    events = load_events(run_dir / ep["trajectory"])
    calls = [e for e in events if e["type"] == "tool_call" and e["tool"] == "issue_refund"]
    assert calls and calls[0]["source"] == "trace" and calls[0].get("mocked") and calls[0]["turn"] == 2
    # a read-only tool really ran against the episode's fixture database
    ep = by_id["run-agent-find-customer-uses"]
    results = [e for e in load_events(run_dir / ep["trajectory"]) if e["type"] == "tool_result" and e["tool"] == "find_customer"]
    assert results and results[0]["source"] == "trace" and "error" in results[0]["content"] or "id" in results[0]["content"]
    # golden examples from evals/ became scenarios and pass with the help-center answer
    assert by_id["run-agent-eval-1"]["passed"]
