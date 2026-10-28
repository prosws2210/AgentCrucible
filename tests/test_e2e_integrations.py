"""End-to-end for the integrations added in 0.2, with no model download:

* OpenAI Responses API through the gateway (streamed and non-streamed), recorded and replayed from the cache
* a remote MCP server reached over Streamable HTTP, with an auth header expanded from ${ENV}
* HTTP mocks: canned responses for a third-party API, plus the http.called / http.not_called checks
* a local MCP server whose database is a per-episode fixture: SQLite always, Postgres when
  CRUCIBLE_TEST_POSTGRES_URL points at a server (CI provides one)
"""

import asyncio
import json
import os
import textwrap
import threading
import time
from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse
from mcp.server.fastmcp import FastMCP
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import PlainTextResponse

from agentcrucible.config import load_config, load_scenarios
from agentcrucible.gateway import free_port
from agentcrucible.runner import Runner, RunOptions

PG_URL = os.environ.get("CRUCIBLE_TEST_POSTGRES_URL")
TOKEN = "notes-secret-token"

AGENT = '''
import json, os, sys, urllib.request
import anyio
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import OpenAI

client = OpenAI()
MODEL = os.environ["CRUCIBLE_MODEL"]


def call_tool(url, name, args):
    async def go():
        async with streamablehttp_client(url) as (r, w, _), ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(name, args)
            return "\\n".join(getattr(c, "text", "") for c in res.content)
    return anyio.run(go)


def tools():
    return [{"type": "function", "name": n, "parameters": {"type": "object"}} for n in ("save_note", "add_order")]


for line in sys.stdin:
    msg = json.loads(line)
    if msg["type"] == "end":
        break
    items = [{"role": "user", "content": msg["content"]}]
    reply = ""
    for step in range(6):
        if step % 2 == 0:  # exercise both wire shapes: streamed and plain
            final = None
            for ev in client.responses.create(model=MODEL, input=items, tools=tools(), stream=True):
                if ev.type == "response.completed":
                    final = ev.response
        else:
            final = client.responses.create(model=MODEL, input=items, tools=tools())
        calls = [o for o in final.output if o.type == "function_call"]
        if not calls:
            reply = final.output_text
            break
        for c in calls:
            server = "notes" if c.name == "save_note" else "store"
            out = call_tool(os.environ[f"CRUCIBLE_MCP_{server.upper()}_URL"], c.name, json.loads(c.arguments))
            items += [{"type": "function_call", "call_id": c.call_id, "name": c.name, "arguments": c.arguments},
                      {"type": "function_call_output", "call_id": c.call_id, "output": out}]
    req = urllib.request.Request(os.environ["CRUCIBLE_HTTP_PAYMENTS_URL"] + "/v1/charges", method="POST",
                                 data=json.dumps({"order": "A-1", "amount": 42}).encode(),
                                 headers={"Content-Type": "application/json"})
    charge = json.loads(urllib.request.urlopen(req).read())
    print(json.dumps({"type": "assistant", "content": f"{reply} Charge {charge['id']} {charge['status']}."}), flush=True)
'''

STORE = '''
import os, sqlite3
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("store")


def run(sql):
    url = os.environ.get("CRUCIBLE_DB_URL")
    if url:
        import psycopg
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql)
        return
    conn = sqlite3.connect(os.environ["CRUCIBLE_DB"])
    conn.execute(sql)
    conn.commit()
    conn.close()


@mcp.tool()
def add_order(id: str, item: str) -> str:
    """Create an order."""
    run(f"INSERT INTO orders (id, item) VALUES ('{id}', '{item}')")
    return f"order {id} created"


mcp.run()
'''

SCENARIO = '''
id: order-and-charge
task: Order a keyboard and note it down.
environment:
  fixtures: {fixture}
  http_mocks:
    payments:
      - {{ method: POST, path: /v1/charges, json: {{ id: ch_123, status: succeeded }} }}
checks:
  - trajectory.call_order: [save_note, add_order]
  - state.sql: {{ db: store, query: "SELECT item FROM orders WHERE id = 'A-1'", expect: keyboard }}
  - http.called: {{ mock: payments, method: POST, path: /v1/charges, body_contains: '"amount": 42' }}
  - http.not_called: {{ mock: payments, method: DELETE }}
  - output.contains: ch_123 succeeded
'''

SCRIPT = [("save_note", {"text": "keyboard ordered"}), ("add_order", {"id": "A-1", "item": "keyboard"}),
          ("text", "Done: keyboard ordered.")]


def fake_responses(seen: list[dict]) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/responses")
    async def responses(req: Request):
        body = await req.json()
        seen.append({"stream": bool(body.get("stream")), "model": body["model"]})
        step = sum(1 for i in body["input"] if isinstance(i, dict) and i.get("type") == "function_call_output")
        name, args = SCRIPT[min(step, len(SCRIPT) - 1)]
        if name == "text":
            item = {"type": "message", "id": f"msg_{step}", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": args, "annotations": []}]}
        else:
            item = {"type": "function_call", "id": f"fc_{step}", "call_id": f"call_{step}", "name": name,
                    "arguments": json.dumps(args), "status": "completed"}
        resp = {"id": f"resp_{step}", "object": "response", "created_at": 0, "model": body["model"],
                "status": "completed", "output": [item], "parallel_tool_calls": True, "tool_choice": "auto",
                "tools": [], "usage": {"input_tokens": 50 + step, "output_tokens": 10, "total_tokens": 60 + step,
                                       "input_tokens_details": {"cached_tokens": 0},
                                       "output_tokens_details": {"reasoning_tokens": 0}}}
        if not body.get("stream"):
            return JSONResponse(resp)

        def sse():
            n = 0

            def ev(kind, **data):
                nonlocal n
                n += 1
                return f"event: {kind}\ndata: {json.dumps({'type': kind, 'sequence_number': n, **data})}\n\n"
            yield ev("response.created", response={**resp, "status": "in_progress", "output": []})
            yield ev("response.output_item.added", output_index=0, item={**item, "status": "in_progress"})
            if item["type"] == "function_call":
                raw = item["arguments"]
                for i in range(0, len(raw), 5):
                    yield ev("response.function_call_arguments.delta", item_id=item["id"], output_index=0,
                             delta=raw[i:i + 5])
            yield ev("response.output_item.done", output_index=0, item=item)
            yield ev("response.completed", response=resp)

        return StreamingResponse(sse(), media_type="text/event-stream")

    return app


def notes_server(auth_seen: list[str]):
    """A remote MCP server that refuses requests without the right bearer token."""
    mcp = FastMCP("notes", stateless_http=True)

    @mcp.tool()
    def save_note(text: str) -> str:
        """Save a note."""
        return f"saved: {text}"

    class RequireToken(BaseHTTPMiddleware):
        async def dispatch(self, request, call_next):
            auth = request.headers.get("authorization", "")
            auth_seen.append(auth)
            if auth != f"Bearer {TOKEN}":
                return PlainTextResponse("unauthorized", 401)
            return await call_next(request)

    app = mcp.streamable_http_app()
    app.add_middleware(RequireToken)
    return app


def start(app) -> tuple[uvicorn.Server, threading.Thread, int]:
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    return server, th, port


def make_project(root: Path, llm_port: int, notes_port: int, fixture: str, cache: str):
    (root / "scenarios").mkdir(parents=True, exist_ok=True)
    (root / "agent.py").write_text(AGENT, encoding="utf-8")
    (root / "store_server.py").write_text(STORE, encoding="utf-8")
    (root / "seed.sql").write_text("CREATE TABLE orders (id TEXT PRIMARY KEY, item TEXT);\n", encoding="utf-8")
    (root / "scenarios" / "order.yaml").write_text(SCENARIO.format(fixture=fixture), encoding="utf-8")
    (root / "crucible.yaml").write_text(textwrap.dedent(f"""
        version: 1
        project: integrations
        agent: {{ transport: stdio, command: python agent.py, turn_timeout_s: 60 }}
        model: fake-model
        llm: {{ upstream_base_url: "http://127.0.0.1:{llm_port}/v1", cache: "{cache}" }}
        mcp_servers:
          notes:
            url: http://127.0.0.1:{notes_port}/mcp
            headers: {{ Authorization: "Bearer ${{NOTES_TOKEN}}" }}
          store: {{ command: python store_server.py }}
        suites:
          main: {{ path: scenarios, runs: 1 }}
    """), encoding="utf-8")
    return load_config(root)


def run_once(cfg):
    pairs = load_scenarios(cfg)
    runner = Runner(cfg, RunOptions(parallel=1, model="fake-model"))
    run = asyncio.run(runner.run([(sc, 1) for sc, _ in pairs]))
    ep = run["episodes"][0]
    events = [json.loads(line) for line in (runner.run_dir / ep["trajectory"]).read_text().splitlines()]
    return ep, events


FIXTURES = [pytest.param("{ store: seed.sql }", id="sqlite"),
            pytest.param("{ store: { postgres: seed.sql } }", id="postgres",
                         marks=pytest.mark.skipif(not PG_URL, reason="set CRUCIBLE_TEST_POSTGRES_URL"))]


@pytest.mark.parametrize("fixture", FIXTURES)
def test_responses_remote_mcp_http_mocks_and_fixtures(tmp_path, monkeypatch, fixture):
    monkeypatch.setenv("NOTES_TOKEN", TOKEN)
    if PG_URL:
        monkeypatch.setenv("CRUCIBLE_POSTGRES_URL", PG_URL)
    seen: list[dict] = []
    auth_seen: list[str] = []
    llm, llm_th, llm_port = start(fake_responses(seen))
    notes, notes_th, notes_port = start(notes_server(auth_seen))
    try:
        cfg = make_project(tmp_path / "p", llm_port, notes_port, fixture, "read_write")
        ep, events = run_once(cfg)
    finally:
        llm.should_exit = True
        llm_th.join(5)

    assert ep["error"] is None, ep["error"]
    assert ep["passed"], [(c["label"], c["passed"], c["detail"]) for c in ep["checks"]]
    assert all(c["passed"] for c in ep["checks"])

    llm_calls = [e for e in events if e["type"] == "llm_call"]
    assert [e["api"] for e in llm_calls] == ["responses"] * 3
    assert [e["stream"] for e in llm_calls] == [True, False, True]
    assert [e["tool_calls"] for e in llm_calls] == [["save_note"], ["add_order"], []]
    assert all(s["model"] == "fake-model" for s in seen)

    # the remote server got the expanded token on every request (and only that token)
    assert auth_seen and set(auth_seen) == {f"Bearer {TOKEN}"}
    results = {e["tool"]: e["content"] for e in events if e["type"] == "tool_result"}
    assert results["save_note"] == "saved: keyboard ordered"

    http = [e for e in events if e["type"] == "http_request"]
    assert [(e["mock"], e["method"], e["path"], e["status"]) for e in http] == [("payments", "POST", "/v1/charges", 200)]

    if PG_URL and "postgres" in fixture:  # the per-episode database was dropped afterwards
        import psycopg
        with psycopg.connect(PG_URL) as conn:
            left = conn.execute("SELECT count(*) FROM pg_database WHERE datname LIKE 'crucible_%'").fetchone()[0]
        assert left == 0

    # Replay with the model server gone: streamed and plain Responses calls both come from the cache.
    try:
        cfg2 = make_project(tmp_path / "p", free_port(), notes_port, fixture, "replay")
        ep2, events2 = run_once(cfg2)
    finally:
        notes.should_exit = True
        notes_th.join(5)
    assert ep2["error"] is None and ep2["passed"], [(c["label"], c["detail"]) for c in ep2["checks"]]
    assert [e["cache"] for e in events2 if e["type"] == "llm_call"] == ["hit"] * 3


def test_remote_mcp_without_token_is_reported(tmp_path, monkeypatch):
    """A wrong header must surface as an episode error, not hang or pass silently."""
    monkeypatch.setenv("NOTES_TOKEN", "wrong")
    seen: list[dict] = []
    llm, llm_th, llm_port = start(fake_responses(seen))
    notes, notes_th, notes_port = start(notes_server([]))
    try:
        cfg = make_project(tmp_path / "p", llm_port, notes_port, "{ store: seed.sql }", "off")
        ep, events = run_once(cfg)
    finally:
        for s, t in ((llm, llm_th), (notes, notes_th)):
            s.should_exit = True
            t.join(5)
    assert not ep["passed"]
    assert "HTTP 401" in (ep["error"] or ""), ep["error"]
    assert not [e for e in events if e["type"] == "llm_call"]  # failed at setup, before the agent ran


def test_connection_check_for_remote_mcp(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from agentcrucible.server import create_app
    monkeypatch.delenv("DATABASE_URL", raising=False)
    notes, notes_th, notes_port = start(notes_server([]))
    try:
        make_project(tmp_path / "p", free_port(), notes_port, "{ store: seed.sql }", "off")
        for token, ok in ((TOKEN, True), ("wrong", False)):
            monkeypatch.setenv("NOTES_TOKEN", token)
            with TestClient(create_app(tmp_path / "p")) as c:
                checks = {x["id"]: x for x in c.get("/api/doctor").json()["checks"]}
                cfg = {s["name"]: s for s in c.get("/api/config").json()["mcp_servers"]}
            assert checks["mcp:notes"]["ok"] is ok, checks["mcp:notes"]
            assert ("save_note" in checks["mcp:notes"]["detail"]) if ok else ("HTTP 401" in checks["mcp:notes"]["detail"])
            assert checks["mcp:store"]["ok"]
            assert token not in json.dumps(cfg)  # header values are never sent to the dashboard
    finally:
        notes.should_exit = True
        notes_th.join(5)
