"""Serve a LlamaIndex agent: workflow agents (`FunctionAgent`, `ReActAgent`, `AgentWorkflow`) or older
`.chat()` agents. Tool calls are read from the workflow's event stream when available."""

from __future__ import annotations

from typing import Any

from . import History, as_text, emit_post_hoc
from . import serve as _serve


def turn_for(agent_or_factory: Any):
    agent = agent_or_factory() if callable(agent_or_factory) and not hasattr(agent_or_factory, "run") \
        and not hasattr(agent_or_factory, "chat") else agent_or_factory

    async def turn(history: History) -> str:
        text = history[-1]["content"]
        try:
            from llama_index.core.llms import ChatMessage
            chat_history = [ChatMessage(role=m["role"], content=m["content"]) for m in history[:-1]]
        except ImportError:
            chat_history = []
        if hasattr(agent, "run"):
            handler = agent.run(user_msg=text, chat_history=chat_history)
            calls = []
            if hasattr(handler, "stream_events"):
                async for ev in handler.stream_events():
                    if type(ev).__name__ == "ToolCallResult":
                        calls.append((ev.tool_name, ev.tool_kwargs or {}, getattr(ev.tool_output, "content", ev.tool_output)))
            response = await handler
            emit_post_hoc(calls)
            return as_text(getattr(response, "response", response))
        if hasattr(agent, "achat"):
            return as_text(await agent.achat(text, chat_history=chat_history))
        return as_text(agent.chat(text, chat_history=chat_history))

    return turn


def serve(agent_or_factory: Any) -> None:
    _serve(turn_for(agent_or_factory))
