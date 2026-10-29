"""Serve a Google ADK agent (`Agent` / `LlmAgent`, with its sub-agents and tools).

ADK calls Gemini directly, which AgentCrucible can't record. So every agent in the tree gets its model replaced by an
OpenAI-compatible one through the episode's gateway (ADK's `LiteLlm`, needs `litellm`), forced to the test model;
pass `keep_model=True` to leave the models alone. Each episode gets one in-memory session; tool calls and results are
read from ADK's event stream.
"""

from __future__ import annotations

import os
from typing import Any

from . import History, as_text, emit_post_hoc
from . import serve as _serve


def _route_models(agent: Any, seen: set[int] | None = None) -> None:
    seen = seen if seen is not None else set()
    if id(agent) in seen:
        return
    seen.add(id(agent))
    if hasattr(agent, "model"):
        try:
            from google.adk.models.lite_llm import LiteLlm
        except ImportError as e:  # pragma: no cover - depends on the user's install
            raise RuntimeError("Routing ADK through AgentCrucible needs litellm: pip install litellm") from e
        agent.model = LiteLlm(model="openai/" + os.environ.get("CRUCIBLE_MODEL", "model"),
                              api_base=os.environ.get("OPENAI_BASE_URL"), api_key=os.environ.get("OPENAI_API_KEY", "x"))
    for sub in getattr(agent, "sub_agents", None) or []:
        _route_models(sub, seen)


def turn_for(agent_or_factory: Any, keep_model: bool = False):
    agent = agent_or_factory() if callable(agent_or_factory) and not hasattr(agent_or_factory, "sub_agents") else agent_or_factory
    if not keep_model:
        _route_models(agent)
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=agent, app_name="agentcrucible")
    state: dict[str, Any] = {}

    async def turn(history: History) -> str:
        if "session" not in state:
            state["session"] = await runner.session_service.create_session(app_name="agentcrucible", user_id="tester")
        message = types.Content(role="user", parts=[types.Part(text=history[-1]["content"])])
        reply, calls, pending = "", [], {}
        async for ev in runner.run_async(user_id="tester", session_id=state["session"].id, new_message=message):
            for call in ev.get_function_calls() or []:
                pending[call.id or call.name] = (call.name, dict(call.args or {}))
            for res in ev.get_function_responses() or []:
                name, args = pending.pop(res.id or res.name, (res.name, {}))
                calls.append((name, args, res.response))
            if ev.content and ev.content.parts and ev.is_final_response():
                reply = "".join(p.text or "" for p in ev.content.parts if getattr(p, "text", None))
        emit_post_hoc(calls)
        return as_text(reply)

    return turn


def serve(agent_or_factory: Any, keep_model: bool = False) -> None:
    _serve(turn_for(agent_or_factory, keep_model))
