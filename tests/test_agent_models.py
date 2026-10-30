"""Per-agent models: an agent's own `model`, a `model_map` for agents that call several models, and `--model` winning."""

import asyncio
import threading
import time

import httpx
import uvicorn
from fastapi import FastAPI, Request

from agentcrucible.config import AgentSpec, LLMSettings, ProjectConfig
from agentcrucible.gateway import EpisodeRoutes, Gateway, free_port
from agentcrucible.runner import Runner, RunOptions
from agentcrucible.trajectory import Recorder


def upstream():
    seen: list[str] = []
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        seen.append(body["model"])
        return {"model": body["model"], "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    return server, port, seen


def test_gateway_forces_the_agents_model_and_maps_several(tmp_path):
    server, port, seen = upstream()
    gw = Gateway(LLMSettings(upstream_base_url=f"http://127.0.0.1:{port}/v1", cache="off"), tmp_path, force_model="project-model")

    async def call(ep_id: str, routes: EpisodeRoutes, model: str) -> None:
        gw.episodes[ep_id] = routes
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw), base_url="http://gw") as c:
            r = await c.post(f"/ep/{ep_id}/v1/chat/completions", json={"model": model, "messages": [{"role": "user", "content": "hi"}]})
            assert r.status_code == 200, r.text

    router = EpisodeRoutes(Recorder("b", "s", 1), model="qwen2.5:7b", model_map={"gpt-4.1-mini": "qwen2.5:3b"})

    async def calls() -> None:  # one event loop: the gateway's client belongs to it
        await call("a", EpisodeRoutes(Recorder("a", "s", 1)), "gpt-4.1")  # no agent model: the project's
        await call("b", router, "gpt-4.1-mini")  # the router's small model
        await call("b", router, "gpt-4.1")  # anything else gets the agent's model
        await gw.client.aclose()

    try:
        asyncio.run(calls())
        assert seen == ["project-model", "qwen2.5:3b", "qwen2.5:7b"]
        assert router.requested_model == "gpt-4.1"  # the reality report still sees what the code asked for
    finally:
        server.should_exit = True


def test_runner_picks_the_model_per_agent(tmp_path):
    (tmp_path / "crucible.yaml").write_text("x", encoding="utf-8")
    cfg = ProjectConfig(project="p", model="project-model", agents={
        "a": AgentSpec(command="python a.py"), "b": AgentSpec(command="python b.py", model="qwen2.5:3b")})
    cfg.root = tmp_path
    r = Runner(cfg, RunOptions())
    assert r.model_for(cfg.agents["a"]) == "project-model" and r.model_for(cfg.agents["b"]) == "qwen2.5:3b"
    forced = Runner(cfg, RunOptions(model="other"))
    assert forced.model_for(cfg.agents["b"]) == "other"  # --model compares models across every agent


def test_gateway_drops_sampling_parameters_the_forced_model_rejects(tmp_path):
    bodies: list[dict] = []
    app = FastAPI()

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        bodies.append(body)
        if "temperature" in body:  # what Claude answers since temperature was removed
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": {"message": "`temperature` is deprecated for this model."}}, 400)
        return {"model": body["model"], "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1}}

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    gw = Gateway(LLMSettings(upstream_base_url=f"http://127.0.0.1:{port}/v1", cache="off"), tmp_path, force_model="claude-x")

    async def calls() -> None:
        gw.episodes["e"] = EpisodeRoutes(Recorder("e", "s", 1))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gw), base_url="http://gw") as c:
            for _ in range(2):
                r = await c.post("/ep/e/v1/chat/completions", json={"model": "gpt-4o", "temperature": 0.2,
                                                                    "messages": [{"role": "user", "content": "hi"}]})
                assert r.status_code == 200, r.text
        await gw.client.aclose()

    try:
        asyncio.run(calls())
        # first call: rejected once, retried without it; second call: dropped up front
        assert ["temperature" in b for b in bodies] == [True, False, False]
    finally:
        server.should_exit = True


def test_models_are_listed_on_anthropic_style_servers_too():
    from fastapi.responses import JSONResponse

    from agentcrucible.gateway import list_models

    app = FastAPI()

    @app.get("/v1/models")
    async def models(req: Request):
        if req.headers.get("x-api-key") != "k":  # Anthropic refuses a Bearer key here
            return JSONResponse({"error": "invalid x-api-key"}, 401)
        return {"data": [{"id": "claude-haiku-5-5"}, {"id": "claude-opus-5-5"}]}

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)
    try:
        ok, names, _ = asyncio.run(list_models(f"http://127.0.0.1:{port}/v1", "k"))
        assert ok and names == ["claude-haiku-5-5", "claude-opus-5-5"]
        ok, names, error = asyncio.run(list_models(f"http://127.0.0.1:{port}/v1", "wrong"))
        assert not ok and "401" in error
    finally:
        server.should_exit = True
