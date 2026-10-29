"""Serve a LangChain `AgentExecutor` (or any Runnable that takes {"input", "chat_history"}).

Compiled LangGraph graphs and LangChain v1 `create_agent(...)` should use the `langgraph` adapter instead.
"""

from __future__ import annotations

from typing import Any

from . import History, as_text, emit_post_hoc
from . import serve as _serve


def turn_for(executor_or_factory: Any, input_key: str = "input"):
    ex = executor_or_factory() if callable(executor_or_factory) and not hasattr(executor_or_factory, "invoke") else executor_or_factory
    try:
        ex.return_intermediate_steps = True
    except Exception:  # noqa: BLE001 - not an AgentExecutor
        pass

    async def turn(history: History) -> str:
        chat_history = [(m["role"].replace("assistant", "ai").replace("user", "human"), m["content"]) for m in history[:-1]]
        payload = {input_key: history[-1]["content"], "chat_history": chat_history}
        result = await ex.ainvoke(payload) if hasattr(ex, "ainvoke") else ex.invoke(payload)
        steps = result.get("intermediate_steps") if isinstance(result, dict) else None
        if steps:
            emit_post_hoc([(getattr(a, "tool", "tool"), a.tool_input if isinstance(getattr(a, "tool_input", None), dict)
                            else {"input": getattr(a, "tool_input", None)}, obs) for a, obs in steps])
        return as_text(result.get("output") if isinstance(result, dict) and "output" in result else result)

    return turn


def serve(executor_or_factory: Any, input_key: str = "input") -> None:
    _serve(turn_for(executor_or_factory, input_key))
