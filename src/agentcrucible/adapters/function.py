"""Serve any Python function (or callable object) as the agent: a hand-written tool loop, a `run_agent()` helper.

The function's parameters decide what it receives:
  (messages | history | conversation | chat_history)  -> the whole conversation as [{"role", "content"}]
  (message, history)                                  -> the latest user message and the earlier turns
  one other parameter (message, text, query, prompt…) -> the latest user message
It may be async, and may return a string or anything `as_text` understands (dict with "content", an object with
`.final_output`, a LangChain message, ...).
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from . import History
from . import serve as _serve

HISTORY_NAMES = ("messages", "history", "conversation", "chat_history", "msgs", "turns")


def turn_for(fn: Callable[..., Any]) -> Callable[[History], Any]:
    try:
        params = [p for p in inspect.signature(fn).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name not in ("self", "cls")]
    except (TypeError, ValueError):
        params = []
    names = [p.name for p in params]

    def turn(history: History) -> Any:
        last = history[-1]["content"] if history else ""
        if names and names[0] in HISTORY_NAMES:
            return fn(history)
        if len(names) >= 2 and names[1] in HISTORY_NAMES:
            return fn(last, history[:-1])
        return fn(last)

    return turn


def serve(fn: Callable[..., Any]) -> None:
    _serve(turn_for(fn))
