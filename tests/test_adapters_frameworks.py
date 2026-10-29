"""The framework adapters against the real libraries: discover -> apply -> smoke run, per framework.

Each case is a tiny agent written with the library's public API (one in-process tool). The scripted model asks for the
tool, then answers. The run must pass, and the tool's call and result must reach the trajectory through the adapter.
Skipped for libraries that aren't installed (they are not AgentCrucible dependencies). To run all six:

    uv run --with crewai --with llama-index-core --with llama-index-llms-openai --with langchain-classic         pytest tests/test_adapters_frameworks.py
"""

import importlib.util
import json
import textwrap
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

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
    "crewai": ("crewai", '''
from crewai import LLM, Agent, Crew, Task
from crewai.tools import tool


@tool("get_weather")''' + TOOL_BODY + '''

llm = LLM(model="openai/gpt-4o-mini")
reporter = Agent(role="Weather reporter", goal="Answer weather questions", backstory="You know the weather.",
                 tools=[get_weather], llm=llm, allow_delegation=False)
task = Task(description="Answer the user: {input}", expected_output="A short answer", agent=reporter)
crew = Crew(agents=[reporter], tasks=[task])
'''),
    "google-adk": ("google.adk", '''
from google.adk.agents import Agent
''' + TOOL_BODY + '''

root_agent = Agent(name="weather", model="gemini-2.0-flash", instruction="You answer weather questions.", tools=[get_weather])
'''),
    "llamaindex": ("llama_index.core", '''
from llama_index.core.agent.workflow import FunctionAgent
from llama_index.llms.openai import OpenAI
''' + TOOL_BODY + '''

agent = FunctionAgent(tools=[get_weather], llm=OpenAI(model="gpt-4o-mini"), system_prompt="You answer weather questions.")
'''),
    "langchain": ("langchain_classic", '''
from langchain_classic.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI


@tool''' + TOOL_BODY + '''

prompt = ChatPromptTemplate.from_messages([("system", "You answer weather questions."), ("placeholder", "{chat_history}"),
                                           ("human", "{input}"), ("placeholder", "{agent_scratchpad}")])
llm = ChatOpenAI(model="gpt-4o-mini")
executor = AgentExecutor(agent=create_tool_calling_agent(llm, [get_weather], prompt), tools=[get_weather])
'''),
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


def _chat(body: dict, msg: dict, usage: dict, finish: str = "stop"):
    if body.get("stream"):  # AgentExecutor and LlamaIndex stream: answer as server-sent events
        delta = {"role": "assistant", "content": msg.get("content") or ""}
        if msg.get("tool_calls"):
            delta["tool_calls"] = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
        base = {"id": "x", "object": "chat.completion.chunk", "created": 0, "model": body["model"]}
        chunks = [{**base, "choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
                  {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": finish}]},
                  {**base, "choices": [], "usage": usage}]
        text = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"
        return StreamingResponse(iter([text]), media_type="text/event-stream")
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
    try:
        found = importlib.util.find_spec(package) is not None
    except ModuleNotFoundError:  # a dotted name whose parent package is missing
        found = False
    if not found:
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
    assert rep["passed"] == rep["episodes"] >= 1, (rep.get("scenarios"), rep["findings"])
    run_dir = repo / "agent-tests" / ".crucible" / "runs" / rep["run_id"]
    run = json.loads((run_dir / "run.json").read_text())
    ep = run["episodes"][0]
    events = load_events(run_dir / ep["trajectory"])
    traced = [e for e in events if e["type"] == "tool_result" and e["tool"] == "get_weather" and e.get("source") == "trace"]
    assert traced and "sunny" in traced[0]["content"], [e for e in events if e["type"] in ("tool_call", "tool_result")]


def test_langgraph_context_schema_and_non_chat_input():
    """Graphs from LangGraph templates: a runtime context with a required field, and an input that isn't a chat."""
    if importlib.util.find_spec("langgraph") is None:
        pytest.skip("langgraph not installed")
    import asyncio
    import dataclasses

    from langgraph.graph import END, START, StateGraph
    from langgraph.runtime import Runtime

    from agentcrucible.adapters.langgraph import turn_for

    @dataclasses.dataclass(kw_only=True)
    class Ctx:
        user_id: str
        model: str = "some/model"

    @dataclasses.dataclass(kw_only=True)
    class Topic:
        topic: str
        extraction_schema: dict

    def greet(state: dict, runtime: Runtime[Ctx]) -> dict:
        return {"messages": [{"role": "assistant", "content": f"hi {runtime.context.user_id} via {runtime.context.model}"}]}

    from typing import Annotated, TypedDict

    from langgraph.graph.message import add_messages

    class Chat(TypedDict):
        messages: Annotated[list, add_messages]

    g = StateGraph(Chat, context_schema=Ctx)
    g.add_node("greet", greet)
    g.add_edge(START, "greet")
    g.add_edge("greet", END)
    assert asyncio.run(turn_for(g.compile())([{"role": "user", "content": "hello"}])) == "hi test via some/model"

    from langgraph.store.base import BaseStore

    async def remember(state: dict, *, store: BaseStore) -> dict:
        await store.aput(("notes",), "1", {"text": "x"})
        found = await store.asearch(("notes",))
        return {"messages": [{"role": "assistant", "content": f"{len(found)} notes"}]}

    g3 = StateGraph(Chat)
    g3.add_node("remember", remember)
    g3.add_edge(START, "remember")
    g3.add_edge("remember", END)
    assert asyncio.run(turn_for(g3.compile())([{"role": "user", "content": "save"}])) == "1 notes"  # a store was given

    def research(state: Topic) -> dict:
        return {"topic": state.topic.upper(), "extraction_schema": state.extraction_schema}

    g2 = StateGraph(Topic)
    g2.add_node("research", research)
    g2.add_edge(START, "research")
    g2.add_edge("research", END)
    out = asyncio.run(turn_for(g2.compile())([{"role": "user", "content": "quantum batteries"}]))
    assert "QUANTUM BATTERIES" in out


def test_openai_agents_typed_context(model_url, monkeypatch):
    if importlib.util.find_spec("agents") is None:
        pytest.skip("openai-agents not installed")
    import asyncio

    from agents import Agent, RunContextWrapper, function_tool
    from pydantic import BaseModel

    from agentcrucible.adapters.openai_agents import turn_for

    class Airline(BaseModel):
        passenger: str | None = None

    seen = []

    @function_tool
    def get_weather(ctx: RunContextWrapper[Airline], city: str) -> str:
        """Get the current weather for a city."""
        seen.append(ctx.context)
        return f"It is sunny in {city}."

    monkeypatch.setenv("OPENAI_BASE_URL", model_url)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    agent = Agent[Airline](name="Weather", instructions="Answer.", tools=[get_weather], model="gpt-4o-mini")
    reply = asyncio.run(turn_for(agent)([{"role": "user", "content": "weather in Berlin?"}]))
    assert "sunny" in reply.lower() and isinstance(seen[0], Airline)  # the tool got a context, not None


def test_pydantic_ai_deps_are_built(model_url, monkeypatch):
    if importlib.util.find_spec("pydantic_ai") is None:
        pytest.skip("pydantic-ai not installed")
    import asyncio
    import dataclasses

    from pydantic_ai import Agent, RunContext

    from agentcrucible.adapters.pydantic_ai import turn_for

    @dataclasses.dataclass
    class Deps:
        customer_id: int

    monkeypatch.setenv("OPENAI_BASE_URL", model_url)
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    agent = Agent("openai:gpt-4o-mini", deps_type=Deps, system_prompt="Answer weather questions.")
    seen = []

    @agent.tool
    def get_weather(ctx: RunContext[Deps], city: str) -> str:
        """Get the current weather for a city."""
        seen.append(ctx.deps)
        return f"It is sunny in {city}."

    reply = asyncio.run(turn_for(agent)([{"role": "user", "content": "weather in Berlin?"}]))
    assert "sunny" in reply.lower() and seen == [Deps(customer_id=1)]
