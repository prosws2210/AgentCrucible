"""Serve an OpenAI Agents SDK `Agent` (`from agents import Agent`): `Runner.run(agent, input=history)`.

The SDK's own trace export is turned off (it would try to upload to OpenAI); tool calls are reported to AgentCrucible
from the run's items instead. Handoffs between agents work as in production. An agent declared with a context type
(`Agent[AirlineContext](...)`) gets one context per episode, built from that type's defaults, as an app would keep.
"""

from __future__ import annotations

import json
from typing import Any

from . import History, as_text, emit_post_hoc, example_instance
from . import serve as _serve


def turn_for(agent_or_factory: Any, max_turns: int = 20):
    from agents import Runner  # imported here so the module loads without the SDK installed
    try:
        from agents import set_tracing_disabled
        set_tracing_disabled(True)
    except ImportError:
        pass
    agent = agent_or_factory() if callable(agent_or_factory) and not hasattr(agent_or_factory, "instructions") else agent_or_factory
    import typing
    ctx_args = typing.get_args(getattr(agent, "__orig_class__", None))
    context = example_instance(ctx_args[0]) if ctx_args and isinstance(ctx_args[0], type) else None

    async def turn(history: History) -> str:
        result = await Runner.run(agent, input=[{"role": m["role"], "content": m["content"]} for m in history],
                                  max_turns=max_turns, **({"context": context} if context is not None else {}))
        calls: dict[str, list[Any]] = {}
        for item in getattr(result, "new_items", []) or []:
            raw = getattr(item, "raw_item", None)
            kind = type(item).__name__
            if kind == "ToolCallItem" and raw is not None:
                name = getattr(raw, "name", None) or (raw.get("name") if isinstance(raw, dict) else None)
                args = getattr(raw, "arguments", None) or (raw.get("arguments") if isinstance(raw, dict) else "{}")
                cid = getattr(raw, "call_id", None) or (raw.get("call_id") if isinstance(raw, dict) else None) or str(len(calls))
                try:
                    parsed = json.loads(args) if isinstance(args, str) else args
                except json.JSONDecodeError:
                    parsed = {"_raw": args}
                calls[cid] = [name, parsed or {}, None]
            elif kind == "ToolCallOutputItem":
                cid = (raw.get("call_id") if isinstance(raw, dict) else getattr(raw, "call_id", None))
                if cid in calls:
                    calls[cid][2] = getattr(item, "output", None)
        emit_post_hoc([tuple(c) for c in calls.values() if c[0]])  # type: ignore[misc]
        return as_text(result.final_output)

    return turn


def serve(agent_or_factory: Any, max_turns: int = 20) -> None:
    _serve(turn_for(agent_or_factory, max_turns))
