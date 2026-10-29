"""Serve a compiled LangGraph graph (or a function that builds one): `graph.invoke({"messages": [...]})`.

Also works for `create_react_agent(...)` and LangChain v1 `create_agent(...)`, which are compiled graphs.
Tool calls are read from the returned messages after each turn (AIMessage.tool_calls + ToolMessage).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from . import History, as_text, emit_post_hoc
from . import serve as _serve


def _get(m: Any, key: str, default: Any = None) -> Any:
    return m.get(key, default) if isinstance(m, dict) else getattr(m, key, default)


def turn_for(graph_or_factory: Any, input_key: str = "messages", config: dict[str, Any] | None = None):
    graph = graph_or_factory() if callable(graph_or_factory) and not hasattr(graph_or_factory, "invoke") else graph_or_factory
    thread = str(uuid.uuid4())

    async def turn(history: History) -> str:
        cfg = {"configurable": {"thread_id": thread}, **(config or {})}
        state = {input_key: [{"role": m["role"], "content": m["content"]} for m in history]}
        if hasattr(graph, "ainvoke"):
            result = await graph.ainvoke(state, cfg)
        else:
            result = graph.invoke(state, cfg)
        msgs = list(_get(result, input_key) or []) if isinstance(result, dict) else []
        new = msgs[len(history):] if len(msgs) > len(history) else msgs
        calls: dict[str, tuple[str, dict[str, Any], Any]] = {}
        for m in new:
            for tc in _get(m, "tool_calls") or []:
                calls[_get(tc, "id") or str(len(calls))] = (_get(tc, "name"), _get(tc, "args") or {}, None)
            if _get(m, "type") == "tool" or type(m).__name__ == "ToolMessage":
                cid = _get(m, "tool_call_id")
                if cid in calls:
                    name, args, _ = calls[cid]
                    calls[cid] = (name, args, _get(m, "content"))
        emit_post_hoc(list(calls.values()))
        last = next((m for m in reversed(new or msgs) if (_get(m, "type") in ("ai", "assistant") or type(m).__name__ == "AIMessage")
                     and _get(m, "content")), None)
        if last is None:
            return as_text(result)
        content = _get(last, "content")
        if isinstance(content, list):  # content blocks
            return "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
        return content if isinstance(content, str) else json.dumps(content, default=str)

    return turn


def serve(graph_or_factory: Any, input_key: str = "messages", config: dict[str, Any] | None = None) -> None:
    _serve(turn_for(graph_or_factory, input_key, config))
