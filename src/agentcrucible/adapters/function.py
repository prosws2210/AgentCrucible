"""Serve any Python function (or callable object) as the agent: a hand-written tool loop, a `run_agent()` helper.

The function's parameters decide what it receives:
  (messages | history | conversation | chat_history)  -> the whole conversation as [{"role", "content"}]
  (message, history)                                  -> the latest user message and the earlier turns
  a parameter named message, text, query, prompt…     -> the latest user message (by keyword if it's keyword-only)
  one other required parameter                         -> the latest user message
It may be async, and may return a string or anything `as_text` understands (dict with "content", an object with
`.final_output`, a LangChain message, ...).
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Callable

from . import History
from . import serve as _serve

HISTORY_NAMES = ("messages", "history", "conversation", "chat_history", "msgs", "turns")
DOCUMENT = re.compile(r"(?i)(pdf|b64|base64|bytes|image|img|file|path|document|doc_|upload|blob|url|workbook|sheet)")
MESSAGE_NAMES = ("message", "msg", "text", "query", "q", "prompt", "question", "input", "user_input", "user_message",
                 "content", "request", "instruction", "task", "utterance", "user_query", "user_text")


def turn_for(fn: Callable[..., Any]) -> Callable[[History], Any]:
    try:
        params = [p for p in inspect.signature(fn).parameters.values()
                  if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY) and p.name not in ("self", "cls")]
    except (TypeError, ValueError):
        params = []
    positional = [p.name for p in params if p.kind != p.KEYWORD_ONLY]
    named = {p.name: p for p in params}
    msg = next((p for p in params if p.name in MESSAGE_NAMES), None)
    hist = next((p for p in params if p.name in HISTORY_NAMES), None)
    required = [p for p in params if p.default is p.empty]
    if msg is None and hist is None and len(required) == 1 and not DOCUMENT.search(required[0].name):
        msg = required[0]  # its only input (a PDF, a file path... isn't something a chat message can be)
    missing = [p.name for p in required if p is not msg and p is not hist]
    if not params or (msg is None and hist is None) or missing:
        sig = ", ".join(named) or "no parameters"
        raise TypeError(f"{getattr(fn, '__name__', fn)}({sig}) can't take a chat message"
                        + (f": it also needs {', '.join(missing)}" if missing and (msg or hist) else "")
                        + ". It isn't a conversational agent; test it from code with real inputs, or wrap it in a function "
                          "that takes the message.")

    def turn(history: History) -> Any:
        last = history[-1]["content"] if history else ""
        args: list[Any] = []
        kwargs: dict[str, Any] = {}
        for p, value in ((msg, last), (hist, history if msg is None else history[:-1])):
            if p is None:
                continue
            if p.kind == p.KEYWORD_ONLY or (args == [] and positional and positional[0] != p.name):
                kwargs[p.name] = value
            else:
                args.append(value)
        return fn(*args, **kwargs)

    return turn


def serve(fn: Callable[..., Any]) -> None:
    _serve(turn_for(fn))
