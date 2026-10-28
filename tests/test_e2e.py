"""End-to-end: real agent process + LLM gateway + MCP gateway + MCP server, with a scripted fake LLM.

No model download needed, so this runs in CI in a few seconds.
"""

import asyncio
import json
import shutil
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request

from agentcrucible.config import load_config, load_scenarios
from agentcrucible.gateway import free_port
from agentcrucible.runner import Runner, RunOptions

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "support-agent"


def fake_llm() -> FastAPI:
    """Scripted 'model': look up the customer, then list orders, then answer."""
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        msgs = body["messages"]
        tool_msgs = [m for m in msgs if m["role"] == "tool"]
        usage = {"prompt_tokens": 100, "completion_tokens": 10, "total_tokens": 110}

        def call(name, args):
            return {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"], "usage": usage,
                    "choices": [{"index": 0, "finish_reason": "tool_calls", "message": {
                        "role": "assistant", "content": "",
                        "tool_calls": [{"id": f"c{len(tool_msgs)}", "type": "function",
                                        "function": {"name": name, "arguments": json.dumps(args)}}]}}]}

        if len(tool_msgs) == 0:
            return call("find_customer", {"email": "ravi@example.com"})
        if len(tool_msgs) == 1:
            return call("list_orders", {"customer_id": 2})
        status = "shipped" if "shipped" in tool_msgs[-1]["content"] else "unknown"
        return {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"], "usage": usage,
                "choices": [{"index": 0, "finish_reason": "stop",
                             "message": {"role": "assistant", "content": f"Your monitor order is {status}."}}]}

    return app


def test_full_episode_through_gateways(tmp_path):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(fake_llm(), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    try:
        project = tmp_path / "project"
        shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".crucible"))
        cfg = load_config(project)
        cfg.llm.upstream_base_url = f"http://127.0.0.1:{port}/v1"
        pairs = load_scenarios(cfg, ids=["order-status-lookup"])
        runner = Runner(cfg, RunOptions(parallel=1, model="fake-model"))
        run = asyncio.run(runner.run([(sc, 2) for sc, _ in pairs]))
    finally:
        server.should_exit = True
        th.join(5)

    assert run["summary"]["n_episodes"] == 2
    ep = run["episodes"][0]
    assert ep["error"] is None, ep["error"]
    assert ep["passed"], ep["checks"]
    events = [json.loads(line) for line in (runner.run_dir / ep["trajectory"]).read_text().splitlines()]
    tools = [e["tool"] for e in events if e["type"] == "tool_call"]
    assert tools == ["find_customer", "list_orders"]
    llm = [e for e in events if e["type"] == "llm_call"]
    assert len(llm) == 3 and all(e["model"] == "fake-model" for e in llm)
    assert run["summary"]["pass_at_1"] == 1.0
