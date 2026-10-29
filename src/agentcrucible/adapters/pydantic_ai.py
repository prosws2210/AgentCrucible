"""Serve a PydanticAI `Agent`: `agent.run(message, message_history=...)`, keeping the conversation between turns."""

from __future__ import annotations

from typing import Any

from . import History, as_text, emit_post_hoc
from . import serve as _serve


def turn_for(agent_or_factory: Any):
    agent = agent_or_factory() if callable(agent_or_factory) and not hasattr(agent_or_factory, "run") else agent_or_factory
    state: dict[str, Any] = {"messages": None}

    async def turn(history: History) -> str:
        result = await agent.run(history[-1]["content"], message_history=state["messages"])
        state["messages"] = result.all_messages()
        calls: dict[str, list[Any]] = {}
        for msg in result.new_messages():
            for part in getattr(msg, "parts", []):
                kind = getattr(part, "part_kind", "")
                if kind == "tool-call":
                    args = part.args_as_dict() if hasattr(part, "args_as_dict") else getattr(part, "args", {})
                    calls[part.tool_call_id] = [part.tool_name, args, None]
                elif kind == "tool-return" and part.tool_call_id in calls:
                    calls[part.tool_call_id][2] = getattr(part, "content", None)
        emit_post_hoc([tuple(c) for c in calls.values()])  # type: ignore[misc]
        return as_text(getattr(result, "output", None) if getattr(result, "output", None) is not None else getattr(result, "data", result))

    return turn


def serve(agent_or_factory: Any) -> None:
    _serve(turn_for(agent_or_factory))
