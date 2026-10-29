"""Serve a compiled LangGraph graph (or a function that builds one): `graph.invoke({"messages": [...]})`.

Also works for `create_react_agent(...)` and LangChain v1 `create_agent(...)`, which are compiled graphs.
Tool calls are read from the returned messages after each turn (AIMessage.tool_calls + ToolMessage).

Graphs that declare a runtime context (`StateGraph(..., context_schema=Context)`) get one built from its defaults,
with test values for required fields. A graph whose input isn't a conversation (no `messages` field) gets the user's
message in its first text field and test values in the others. A graph compiled without a store (LangGraph Platform
adds one) gets an empty in-memory store per episode.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from . import History, as_text, emit_post_hoc, example_instance, schema_fields
from . import serve as _serve


def _get(m: Any, key: str, default: Any = None) -> Any:
    return m.get(key, default) if isinstance(m, dict) else getattr(m, key, default)


def turn_for(graph_or_factory: Any, input_key: str = "messages", config: dict[str, Any] | None = None):
    graph = graph_or_factory() if callable(graph_or_factory) and not hasattr(graph_or_factory, "invoke") else graph_or_factory
    thread = str(uuid.uuid4())
    if getattr(graph, "store", "absent") is None:  # LangGraph Platform injects a store; tests get a fresh one per episode
        try:
            from langgraph.store.memory import InMemoryStore
            graph.store = InMemoryStore()
        except Exception:  # noqa: BLE001 - older langgraph
            pass
    builder = getattr(graph, "builder", None)
    ctx_schema = getattr(builder, "context_schema", None) or getattr(graph, "context_schema", None)
    context = example_instance(ctx_schema) if isinstance(ctx_schema, type) else None
    in_schema = getattr(builder, "input_schema", None) or getattr(graph, "input_schema", None)
    fields = schema_fields(in_schema) if isinstance(in_schema, type) else {}
    chat = not fields or input_key in fields

    def make_state(history: History) -> Any:
        if chat:
            return {input_key: [{"role": m["role"], "content": m["content"]} for m in history]}
        text_field = next((n for n, t in fields.items() if t is str), next(iter(fields)))
        obj = example_instance(in_schema, {text_field: history[-1]["content"]})
        return obj if obj is not None else {text_field: history[-1]["content"]}

    # templates that declare context_schema but still read settings from config["configurable"] get them there too
    ctx_values = {k: getattr(context, k) for k in schema_fields(type(context))} if context is not None else {}

    async def turn(history: History) -> str:
        cfg = {"configurable": {**ctx_values, "thread_id": thread}, **(config or {})}
        state = make_state(history)
        kw = {"context": context} if context is not None else {}
        if hasattr(graph, "ainvoke"):
            result = await graph.ainvoke(state, cfg, **kw)
        else:
            result = graph.invoke(state, cfg, **kw)
        if not chat:  # a structured result, not a conversation: show it as the answer
            return as_text(result) if not isinstance(result, dict) else json.dumps(result, default=str)[:4000]
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
