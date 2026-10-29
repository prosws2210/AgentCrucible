"""The framework adapters against the real libraries: discover -> apply -> smoke run, per framework.

Each case is a tiny agent written with the library's public API (one in-process tool). The scripted model asks for the
tool, then answers. The run must pass, and the tool's call and result must reach the trajectory through the adapter.
Skipped for libraries that aren't installed (they are not AgentCrucible dependencies).
"""

import importlib.util
import json
import textwrap
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, Request

from agentcrucible.discover import apply, build_plan, discover
from agentcrucible.gateway import free_port
from agentcrucible.trajectory import load_events

TOOL_BODY = '''
def get_weather(city: str) -> str:
    """Get the current weather for a city."""
    return f"It is sunny and 21C in {city}."
'''

CASES = {
    "langgraph": ("langgraph", '''
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent


@tool''' + TOOL_BODY + '''

model = ChatOpenAI(model="gpt-4o-mini")
graph = create_react_agent(model, tools=[get_weather], prompt="You answer weather questions.")
'''),
    "openai-agents": ("agents", '''
from agents import Agent, function_tool


@function_tool''' + TOOL_BODY + '''

weather_agent = Agent(name="Weather", instructions="You answer weather questions.", tools=[get_weather], model="gpt-4o-mini")
'''),
    "pydantic-ai": ("pydantic_ai", '''
from pydantic_ai import Agent

agent = Agent("openai:gpt-4o-mini", system_prompt="You answer weather questions.")


@agent.tool_plain''' + TOOL_BODY),
}


def fake_model() -> FastAPI:
    app = FastAPI()
    usage_c = {"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}

    @app.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        msgs = body["messages"]
        if not body.get("tools"):
            return _chat(body, {"content": "Yes, go ahead."}, usage_c)
        if any(m.get("role") == "tool" for m in msgs):
            return _chat(body, {"content": "It is sunny in Berlin today."}, usage_c)
        return _chat(body, {"content": None, "tool_calls": [{"id": "call_1", "type": "function", "function": {
            "name": "get_weather", "arguments": json.dumps({"city": "Berlin"})}}]}, usage_c, "tool_calls")

    @app.post("/v1/responses")
    async def responses(req: Request):
        body = await req.json()
        items = body["input"] if isinstance(body["input"], list) else []
        done = any(isinstance(i, dict) and i.get("type") == "function_call_output" for i in items)
        if done:
            item = {"type": "message", "id": "msg_1", "role": "assistant", "status": "completed",
                    "content": [{"type": "output_text", "text": "It is sunny in Berlin today.", "annotations": []}]}
        else:
            item = {"type": "function_call", "id": "fc_1", "call_id": "call_1", "name": "get_weather",
                    "arguments": json.dumps({"city": "Berlin"}), "status": "completed"}
        return {"id": "resp_1", "object": "response", "created_at": 0, "model": body["model"], "status": "completed",
                "output": [item], "parallel_tool_calls": True, "tool_choice": "auto", "tools": [],
                "usage": {"input_tokens": 40, "output_tokens": 8, "total_tokens": 48,
                          "input_tokens_details": {"cached_tokens": 0}, "output_tokens_details": {"reasoning_tokens": 0}}}

    return app


def _chat(body: dict, msg: dict, usage: dict, finish: str = "stop") -> dict:
    return {"id": "x", "object": "chat.completion", "created": 0, "model": body["model"], "usage": usage,
            "choices": [{"index": 0, "finish_reason": finish, "message": {"role": "assistant", **msg}}]}


@pytest.fixture(scope="module")
def model_url():
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(fake_model(), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/v1"
    server.should_exit = True
    th.join(5)


@pytest.mark.parametrize("framework", list(CASES))
def test_framework_adapter(tmp_path, model_url, framework):
    package, code = CASES[framework]
    if importlib.util.find_spec(package) is None:
        pytest.skip(f"{package} not installed")
    repo = tmp_path / "repo"
    (repo / "weather").mkdir(parents=True)
    (repo / "weather" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "weather" / "agent.py").write_text(textwrap.dedent(code), encoding="utf-8")

    d = discover(repo)
    agents = [a for a in d.agents if a.include]
    assert len(agents) == 1 and agents[0].framework == framework, [(a.name, a.framework) for a in d.agents]
    assert agents[0].tools == ["get_weather"]
    build_plan(d, repo)
    assert d.plans[0].strategy == "code", d.plans[0]
    result = apply(d, repo, model="fake-model", upstream=model_url)
    rep = result["reality"]
    assert rep["errors"] == 0, rep["findings"]
    assert rep["passed"] == rep["episodes"] >= 1, rep
    run_dir = repo / "agent-tests" / ".crucible" / "runs" / rep["run_id"]
    run = json.loads((run_dir / "run.json").read_text())
    ep = run["episodes"][0]
    events = load_events(run_dir / ep["trajectory"])
    traced = [e for e in events if e["type"] == "tool_result" and e["tool"] == "get_weather" and e.get("source") == "trace"]
    assert traced and "sunny" in traced[0]["content"], [e for e in events if e["type"] in ("tool_call", "tool_result")]
