"""End-to-end for gaps 1-3 with no model download:

* HTTP agent transport: the real examples/coding-agent service (Anthropic SDK, streaming) is started by the runner
* Anthropic Messages API through the gateway, streamed, with tool_use input split across many chunks
* workspace fixture + state.command / state.git_diff / state.file graders
* cache: a second run replays the recorded streams with the fake model server shut down
"""

import asyncio
import json
import shutil
import threading
import time
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

from agentcrucible.config import load_config, load_scenarios
from agentcrucible.gateway import free_port
from agentcrucible.runner import Runner, RunOptions

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "coding-agent"
FIXED = '''"""Pricing helpers used by the checkout service."""


def apply_discount(price: float, percent: float) -> float:
    """Return the price after taking `percent` percent off, rounded to cents."""
    if not 0 <= percent <= 100:
        raise ValueError("percent must be between 0 and 100")
    return round(price * (1 - percent / 100), 2)


def total(prices: list[float]) -> float:
    """Sum of prices, rounded to cents."""
    return round(sum(prices), 2)
'''

SCRIPT = [
    ("tool_use", "list_files", {}),
    ("tool_use", "read_file", {"path": "calc.py"}),
    ("tool_use", "write_file", {"path": "calc.py", "content": FIXED}),
    ("tool_use", "run_tests", {}),
    ("text", "Fixed apply_discount to subtract the discount; all tests pass.", None),
]


def fake_anthropic(hits: list[str]) -> FastAPI:
    app = FastAPI()

    @app.post("/v1/messages")
    async def messages(req: Request):
        body = await req.json()
        hits.append(req.headers.get("anthropic-version", ""))
        step = sum(1 for m in body["messages"] if m["role"] == "user" and isinstance(m["content"], list))
        kind, name, args = SCRIPT[min(step, len(SCRIPT) - 1)]
        block = ({"type": "tool_use", "id": f"toolu_{step}", "name": name, "input": args} if kind == "tool_use"
                 else {"type": "text", "text": name})
        stop = "tool_use" if kind == "tool_use" else "end_turn"
        msg = {"id": f"msg_{step}", "type": "message", "role": "assistant", "model": body["model"],
               "content": [block], "stop_reason": stop, "usage": {"input_tokens": 100 + step, "output_tokens": 20}}
        if not body.get("stream"):
            return JSONResponse(msg)

        def sse():
            def ev(name, data):
                return f"event: {name}\ndata: {json.dumps(data)}\n\n"
            yield ev("message_start", {"type": "message_start", "message": {**msg, "content": [], "stop_reason": None,
                                                                             "usage": {"input_tokens": 100 + step, "output_tokens": 0}}})
            if kind == "tool_use":
                yield ev("content_block_start", {"type": "content_block_start", "index": 0,
                                                 "content_block": {**block, "input": {}}})
                raw = json.dumps(args)
                for i in range(0, len(raw), 7):  # split the JSON awkwardly, like real streams do
                    yield ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                     "delta": {"type": "input_json_delta", "partial_json": raw[i:i + 7]}})
            else:
                yield ev("content_block_start", {"type": "content_block_start", "index": 0,
                                                 "content_block": {"type": "text", "text": ""}})
                for word in name.split(" "):
                    yield ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                                     "delta": {"type": "text_delta", "text": word + " "}})
            yield ev("content_block_stop", {"type": "content_block_stop", "index": 0})
            yield ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": stop},
                                       "usage": {"output_tokens": 20}})
            yield ev("message_stop", {"type": "message_stop"})

        return StreamingResponse(sse(), media_type="text/event-stream")

    return app


def start(app: FastAPI) -> tuple[uvicorn.Server, threading.Thread, int]:
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    return server, th, port


def project(tmp_path: Path, llm_port: int, cache: str):
    cfg = load_config(tmp_path / "project")
    cfg.llm.upstream_base_url = f"http://127.0.0.1:{llm_port}/v1"
    cfg.llm.cache = cache  # type: ignore[assignment]
    agent_port = free_port()
    cfg.agent.url = f"http://127.0.0.1:{agent_port}/turn"
    cfg.agent.command = f"python agent_service.py --port {agent_port}"
    return cfg


def test_http_anthropic_streaming_coding_agent(tmp_path):
    shutil.copytree(EXAMPLE, tmp_path / "project", ignore=shutil.ignore_patterns(".crucible"))
    hits: list[str] = []
    server, th, port = start(fake_anthropic(hits))
    try:
        cfg = project(tmp_path, port, "read_write")
        pairs = load_scenarios(cfg, ids=["fix-failing-test"])
        runner = Runner(cfg, RunOptions(parallel=1, model="fake-claude"))
        run = asyncio.run(runner.run([(sc, 1) for sc, _ in pairs]))
    finally:
        server.should_exit = True
        th.join(5)

    ep = run["episodes"][0]
    assert ep["error"] is None, ep["error"]
    assert ep["passed"], [(c["label"], c["detail"]) for c in ep["checks"]]
    assert run["transport"] == "http"
    assert hits and all(h for h in hits)  # anthropic-version header forwarded

    events = [json.loads(line) for line in (runner.run_dir / ep["trajectory"]).read_text().splitlines()]
    llm = [e for e in events if e["type"] == "llm_call"]
    assert len(llm) == 5
    assert all(e["api"] == "anthropic" and e["stream"] and e["model"] == "fake-claude" for e in llm)
    assert [e["tool_calls"] for e in llm][:4] == [["list_files"], ["read_file"], ["write_file"], ["run_tests"]]
    writes = [e for e in events if e["type"] == "tool_call" and e["tool"] == "write_file"]
    assert writes[0]["args"]["content"] == FIXED  # multi-line input survived chunked input_json_delta relay
    results = [e for e in events if e["type"] == "tool_result" and e["tool"] == "run_tests"]
    assert "exit code 0" in results[0]["content"]

    # Replay: the fake model server is gone; every stream must be rebuilt from the cache.
    cfg2 = project(tmp_path, free_port(), "replay")
    pairs = load_scenarios(cfg2, ids=["fix-failing-test"])
    runner2 = Runner(cfg2, RunOptions(parallel=1, model="fake-claude"))
    run2 = asyncio.run(runner2.run([(sc, 1) for sc, _ in pairs]))
    ep2 = run2["episodes"][0]
    assert ep2["error"] is None and ep2["passed"], [(c["label"], c["detail"]) for c in ep2["checks"]]
    replayed = [json.loads(line) for line in (runner2.run_dir / ep2["trajectory"]).read_text().splitlines()]
    caches = [e["cache"] for e in replayed if e["type"] == "llm_call"]
    # pytest timings in run_tests output change between runs, so later calls are served by position
    assert len(caches) == 5 and set(caches) <= {"hit", "hit-seq"}, caches
