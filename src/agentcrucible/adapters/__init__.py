"""Adapters that let AgentCrucible drive an agent that is only an object in your code.

A generated adapter (written by `crucible discover --apply`) is a few lines:

    from agentcrucible.adapters import prepare, langgraph
    prepare(env_map={"DATABASE_URL": "db:app"}, tool_modules=["app.tools"], tools=["refund_order"])
    from app.agents.support import graph
    langgraph.serve(graph)

`serve` speaks AgentCrucible's stdio protocol (one JSON line per turn). `prepare` runs before your code is imported:
it points your app's own settings at the episode's fixtures and mocks, and wraps tools that run inside the agent's
process so their calls are traced to the gateway and scenario mocks / blocked tools apply to them too.
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import inspect
import json
import os
import re
import sys
import tempfile
import threading
import time
import urllib.request
from typing import Any, Awaitable, Callable

History = list[dict[str, str]]
Turn = Callable[[History], "str | Awaitable[str]"]

_REPORTED: set[str] = set()  # tools a wrapper reported during the current turn (post-hoc tracing skips them)


# ---------------------------------------------------------------- protocol


def serve(turn: Turn) -> None:
    """Run the stdio protocol: read `{"type": "user", "content": ...}` lines, answer `{"type": "assistant", ...}`."""
    history: History = []
    out = sys.stdout
    sys.stdout = sys.stderr  # stray print() calls in the agent must not corrupt the protocol
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "end":
            break
        if msg.get("type") != "user":
            continue
        history.append({"role": "user", "content": str(msg.get("content", ""))})
        _REPORTED.clear()
        try:
            reply = run_sync(turn(list(history)))
            reply = as_text(reply)
        except Exception as e:  # noqa: BLE001 - report the failure as the turn's answer, keep the episode going
            import traceback
            traceback.print_exc(file=sys.stderr)
            reply = f"[agent error] {type(e).__name__}: {e}"
        history.append({"role": "assistant", "content": reply})
        out.write(json.dumps({"type": "assistant", "content": reply}) + "\n")
        out.flush()


_LOOP: asyncio.AbstractEventLoop | None = None


def _loop() -> asyncio.AbstractEventLoop:
    """One event loop for the whole conversation, on its own thread. A loop per turn (asyncio.run) closes when the turn
    ends, and clients the agent created on it (httpx, the OpenAI SDK) fail on the next turn: "Event loop is closed"."""
    global _LOOP
    if _LOOP is None:
        _LOOP = asyncio.new_event_loop()
        threading.Thread(target=_LOOP.run_forever, daemon=True, name="agentcrucible-loop").start()
    return _LOOP


def run_sync(value: Any) -> Any:
    if inspect.isawaitable(value):
        return asyncio.run_coroutine_threadsafe(_await(value), _loop()).result()
    return value


async def _await(v: Awaitable[Any]) -> Any:
    return await v


def as_text(reply: Any) -> str:
    """Pull the answer out of whatever the agent returned."""
    if reply is None:
        return ""
    if isinstance(reply, str):
        return reply
    for attr in ("final_output", "output", "content", "text", "raw", "response", "data"):
        v = getattr(reply, attr, None)
        if isinstance(v, str):
            return v
        if v is not None and attr in ("final_output", "output", "data", "response"):
            return as_text(v)
    if isinstance(reply, dict):
        for key in ("content", "reply", "output", "response", "answer", "text", "message", "result"):
            if key in reply:
                v = reply[key]
                return v if isinstance(v, str) else as_text(v)
        msgs = reply.get("messages")
        if isinstance(msgs, list) and msgs:
            return as_text(msgs[-1])
    if isinstance(reply, list) and reply:
        return as_text(reply[-1])
    return str(reply)


def as_message(history: list[dict[str, str]]) -> str:
    """The latest user message, with the conversation so far in front of it, for agents that take one message per call
    and keep no memory between calls (a task dict): without it, details given two turns ago are lost."""
    if len(history) <= 1:
        return history[-1]["content"] if history else ""
    earlier = "\n".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in history[:-1])
    return f"Conversation so far:\n{earlier}\n\nLatest message from the user:\n{history[-1]['content']}"


DOC_PATH = re.compile(r"""[\w./\\:-]*[\w-]\.(?:pdf|png|jpe?g|tiff?|webp|gif|bmp|docx?|xlsx?|xls|csv|txt|pptx?|json|md|html?)\b""", re.I)


def document_from(history: list[dict[str, str]]) -> str:
    """The document a turn is about, for agents that take a file rather than a message: a path named in the
    conversation (latest first) that exists, else the latest message saved as a text file."""
    for m in reversed(history):
        if m.get("role") != "user":
            continue
        for p in DOC_PATH.findall(m.get("content") or ""):
            if os.path.isfile(p):
                return os.path.abspath(p)
    fd, path = tempfile.mkstemp(prefix="crucible-doc-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(history[-1]["content"] if history else "")
    return path


def chat_model() -> Any:
    """A LangChain chat model on AgentCrucible's gateway, for agents that take one (`Agent(llm=chat_model())`).
    Uses the OpenAI-format endpoint with langchain_openai, else the Anthropic one with langchain_anthropic."""
    model = os.environ.get("CRUCIBLE_MODEL") or "agentcrucible"
    try:
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(model=model, base_url=os.environ.get("OPENAI_BASE_URL"), api_key=os.environ.get("OPENAI_API_KEY") or "agentcrucible")
    except ImportError:
        pass
    try:
        from langchain_anthropic import ChatAnthropic
        return ChatAnthropic(model=model, base_url=os.environ.get("ANTHROPIC_BASE_URL"),  # type: ignore[call-arg]
                             api_key=os.environ.get("ANTHROPIC_API_KEY") or "agentcrucible")
    except ImportError:
        raise ImportError("chat_model() needs langchain_openai or langchain_anthropic in the agent's environment; "
                          "or pass your own client to the agent in this adapter") from None


# ---------------------------------------------------------------- environment


def prepare(env_map: dict[str, str] | None = None, tool_modules: list[str] | None = None, tools: list[str] | None = None,
            dispatch: dict[str, list[str]] | None = None, sys_path: list[str] | None = None,
            workspace: bool = False) -> None:
    """Call before importing the agent.

    env_map: your setting -> what to point it at: "db:<fixture>" (the episode's database as a URL), "dbpath:<fixture>"
             (as a file path), "http:<mock>" (an HTTP mock's base URL), "openai" / "anthropic" (the model gateway),
             "redis" (the episode's own empty Redis database, when the run has a Redis server).
    tool_modules + tools: modules to import first and the tool names in them to wrap (traced, mockable, blockable).
    dispatch: {"app.agent": ["TOOLS"]}: name->function tables of a hand-written tool loop to wrap in place.
    workspace: run in the episode's fresh copy of the repository (CRUCIBLE_WORKSPACE), so files the tools read or
               write are the copy's. Code is still imported from where it is.
    """
    for p in sys_path or []:
        p = os.path.abspath(p)
        if p in sys.path:  # ahead of the adapter's own folder, so `weather.agent` isn't adapters/weather.py
            sys.path.remove(p)
        sys.path.insert(0, p)
    apply_env_map(env_map or {})
    names = set(tools or [])
    for mod_name in tool_modules or []:
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:  # noqa: BLE001
            print(f"[agentcrucible] could not import {mod_name} to trace its tools: {e}", file=sys.stderr)
            continue
        for attr in list(vars(mod)):
            obj = getattr(mod, attr)
            tname = _tool_name(obj, attr)
            if tname in names:
                wrapped = instrument(obj, tname)
                if wrapped is not obj:
                    setattr(mod, attr, wrapped)
    for mod_name, tables in (dispatch or {}).items():
        try:
            mod = importlib.import_module(mod_name)
        except Exception as e:  # noqa: BLE001
            print(f"[agentcrucible] could not import {mod_name}: {e}", file=sys.stderr)
            continue
        for table in tables:
            d = getattr(mod, table, None)
            if isinstance(d, dict):
                for k, fn in list(d.items()):
                    if callable(fn):
                        d[k] = instrument(fn, str(k))
    if workspace and os.environ.get("CRUCIBLE_WORKSPACE"):
        os.chdir(os.environ["CRUCIBLE_WORKSPACE"])


def apply_env_map(env_map: dict[str, str]) -> None:
    for setting, target in env_map.items():
        kind, _, name = target.partition(":")
        key = name.upper().replace("-", "_")
        value = None
        if kind == "db":
            url = os.environ.get(f"CRUCIBLE_DB_{key}_URL")
            path = os.environ.get(f"CRUCIBLE_DB_{key}")
            value = url or (f"sqlite:///{path}" if path else None)
        elif kind == "dbpath":
            value = os.environ.get(f"CRUCIBLE_DB_{key}")
        elif kind == "redis":  # this episode's own empty Redis database
            value = os.environ.get("CRUCIBLE_REDIS_URL")
        elif kind == "http":
            value = os.environ.get(f"CRUCIBLE_HTTP_{key}_URL")
        elif kind == "openai":
            value = os.environ.get("OPENAI_BASE_URL")
        elif kind == "anthropic":
            value = os.environ.get("ANTHROPIC_BASE_URL")
        elif kind == "value":
            value = name
        if value is not None:
            os.environ[setting] = value


# ---------------------------------------------------------------- tool tracing, mocks and blocked tools


def emit(*events: dict[str, Any]) -> None:
    """Report tool events to the gateway (best effort: tracing must never break the agent)."""
    url = os.environ.get("CRUCIBLE_EVENTS_URL")
    if not url or not events:
        return
    try:
        req = urllib.request.Request(url, data=json.dumps(list(events), default=str).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as e:  # noqa: BLE001
        print(f"[agentcrucible] tracing failed: {e}", file=sys.stderr)


def _policy(name: str) -> tuple[bool, Any, bool]:
    """(blocked, mock value, mocked)"""
    try:
        deny = json.loads(os.environ.get("CRUCIBLE_DENY_TOOLS") or "[]")
        mocks = json.loads(os.environ.get("CRUCIBLE_TOOL_MOCKS") or "{}")
    except json.JSONDecodeError:
        deny, mocks = [], {}
    return name in deny, mocks.get(name), name in mocks


def _call_args(fn: Callable[..., Any], args: tuple, kwargs: dict[str, Any]) -> dict[str, Any]:
    try:
        bound = inspect.signature(fn).bind_partial(*args, **kwargs)
        return {k: v for k, v in bound.arguments.items() if k not in ("self", "ctx", "context", "run_context", "config")}
    except (TypeError, ValueError):
        return {"args": list(args), **kwargs}


def _wrap_callable(fn: Callable[..., Any], name: str) -> Callable[..., Any]:
    if getattr(fn, "__crucible_traced__", False):
        return fn

    def before(args: tuple, kwargs: dict[str, Any]) -> tuple[bool, Any]:
        blocked, mock, mocked = _policy(name)
        _REPORTED.add(name)
        ev = {"type": "tool_call", "tool": name, "args": _call_args(fn, args, kwargs)}
        if blocked:
            ev["blocked"] = True
            text = f"Tool '{name}' is blocked by test policy."
            emit(ev, {"type": "tool_result", "tool": name, "content": text, "is_error": True})
            return True, text
        if mocked:
            ev["mocked"] = True
            from ..snapshot import answer, is_snapshot_mock
            if is_snapshot_mock(mock):  # a retriever answered from the document snapshot
                mock = answer(mock, ev["args"])
            text = mock if isinstance(mock, str) else json.dumps(mock)
            emit(ev, {"type": "tool_result", "tool": name, "content": text})
            return True, mock
        emit(ev)
        return False, None

    def after(result: Any, start: float, error: BaseException | None) -> None:
        if error is None:
            result = _inject(name, result)
        emit({"type": "tool_result", "tool": name, "content": f"{type(error).__name__}: {error}" if error else _short(result),
              "is_error": error is not None, "duration_ms": (time.monotonic() - start) * 1000})

    if inspect.iscoroutinefunction(fn):
        @functools.wraps(fn)
        async def awrapper(*args: Any, **kwargs: Any) -> Any:
            done, value = before(args, kwargs)
            if done:
                return value
            start = time.monotonic()
            try:
                result = await fn(*args, **kwargs)
            except BaseException as e:
                after(None, start, e)
                raise
            after(result, start, None)
            return _inject(name, result)
        awrapper.__crucible_traced__ = True  # type: ignore[attr-defined]
        return awrapper

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        done, value = before(args, kwargs)
        if done:
            return value
        start = time.monotonic()
        try:
            result = fn(*args, **kwargs)
        except BaseException as e:
            after(None, start, e)
            raise
        after(result, start, None)
        return _inject(name, result)
    wrapper.__crucible_traced__ = True  # type: ignore[attr-defined]
    return wrapper


def _inject(name: str, result: Any) -> Any:
    """Append a scenario's `inject` text to a tool's real output (prompt-injection tests)."""
    try:
        text = json.loads(os.environ.get("CRUCIBLE_TOOL_INJECT") or "{}").get(name)
    except json.JSONDecodeError:
        text = None
    if not text:
        return result
    if isinstance(result, str):
        return result + "\n\n" + text
    if isinstance(result, (dict, list)):
        return json.dumps(result, default=str) + "\n\n" + text
    return f"{result}\n\n{text}"


def _short(v: Any, limit: int = 4000) -> str:
    s = v if isinstance(v, str) else json.dumps(v, default=str) if isinstance(v, (dict, list)) else str(v)
    return s[:limit]


def _tool_name(obj: Any, attr: str) -> str:
    return str(getattr(obj, "name", None) or getattr(getattr(obj, "metadata", None), "name", None) or attr) \
        if not inspect.isfunction(obj) else attr


def instrument(obj: Any, name: str) -> Any:
    """Wrap one tool, whatever framework made it. Returns the object to use instead (often the same one)."""
    if inspect.isfunction(obj) or inspect.ismethod(obj):
        return _wrap_callable(obj, name)
    # LangChain StructuredTool / Tool
    for attr in ("func", "coroutine"):
        fn = getattr(obj, attr, None)
        if callable(fn):
            try:
                object.__setattr__(obj, attr, _wrap_callable(fn, name))
            except Exception:  # noqa: BLE001
                pass
    # OpenAI Agents SDK FunctionTool
    inv = getattr(obj, "on_invoke_tool", None)
    if callable(inv):
        async def on_invoke(ctx: Any, input_json: str, _inv: Any = inv) -> Any:
            try:
                args = json.loads(input_json or "{}")
            except json.JSONDecodeError:
                args = {"_raw": input_json}
            _REPORTED.add(name)
            blocked, mock, mocked = _policy(name)
            ev = {"type": "tool_call", "tool": name, "args": args, **({"blocked": True} if blocked else {}),
                  **({"mocked": True} if mocked else {})}
            if blocked or mocked:
                text = f"Tool '{name}' is blocked by test policy." if blocked else (mock if isinstance(mock, str) else json.dumps(mock))
                emit(ev, {"type": "tool_result", "tool": name, "content": text, "is_error": blocked})
                return text
            emit(ev)
            start = time.monotonic()
            try:
                out = await _inv(ctx, input_json)
            except BaseException as e:
                emit({"type": "tool_result", "tool": name, "content": f"{type(e).__name__}: {e}", "is_error": True})
                raise
            emit({"type": "tool_result", "tool": name, "content": _short(out), "duration_ms": (time.monotonic() - start) * 1000})
            return out
        try:
            object.__setattr__(obj, "on_invoke_tool", on_invoke)
        except Exception:  # noqa: BLE001
            pass
    # CrewAI BaseTool
    run = getattr(type(obj), "_run", None)
    if callable(run) and not hasattr(obj, "on_invoke_tool") and not hasattr(obj, "func"):
        bound = obj._run
        try:
            object.__setattr__(obj, "_run", _wrap_callable(bound, name))
        except Exception:  # noqa: BLE001
            pass
    return obj


def traced(name: str) -> bool:
    return name in _REPORTED


def emit_post_hoc(calls: list[tuple[str, dict[str, Any], Any]]) -> None:
    """Report tool calls read from a framework's result after the turn, for tools no wrapper saw."""
    events: list[dict[str, Any]] = []
    for name, args, result in calls:
        if traced(name):
            continue
        events.append({"type": "tool_call", "tool": name, "args": args if isinstance(args, dict) else {"input": args}})
        if result is not None:
            events.append({"type": "tool_result", "tool": name, "content": _short(result)})
    emit(*events)


# ---------------------------------------------------------------- context and input objects


def example_value(tp: Any, depth: int = 0) -> Any:
    """A plausible test value for a type annotation (for fields a context or input object requires)."""
    import typing
    origin = typing.get_origin(tp)
    args = typing.get_args(tp)
    if tp is None or tp is type(None) or depth > 4:
        return None
    if origin is typing.Union or str(origin) == "<class 'types.UnionType'>":
        return None if type(None) in args else example_value(args[0], depth + 1)
    if origin is typing.Annotated:
        return example_value(args[0], depth + 1)
    if origin is typing.Literal:
        return args[0] if args else None
    if origin in (list, set, tuple) or tp in (list, set, tuple):
        return []
    if origin is dict or tp is dict:
        return {}
    if tp is str:
        return "test"
    if tp is bool:
        return False
    if tp is int:
        return 1
    if tp is float:
        return 1.0
    if isinstance(tp, type):
        return example_instance(tp, depth=depth + 1)
    return None


def example_instance(cls: Any, overrides: dict[str, Any] | None = None, depth: int = 0) -> Any:
    """An instance of a dataclass, pydantic model or TypedDict with its defaults, and test values for required
    fields: a graph's runtime context, an agent's typed context, or a graph input that isn't a chat."""
    import dataclasses
    import typing
    overrides = overrides or {}
    try:
        hints = typing.get_type_hints(cls, include_extras=True)
    except Exception:  # noqa: BLE001 - unresolvable forward references
        hints = getattr(cls, "__annotations__", {}) or {}
    try:
        if dataclasses.is_dataclass(cls):
            values = {f.name: overrides.get(f.name, example_value(hints.get(f.name, f.type), depth))
                      for f in dataclasses.fields(cls) if f.init and (f.name in overrides or (
                          f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING))}
            return cls(**values)
        fields = getattr(cls, "model_fields", None)
        if fields is not None:  # pydantic: built without validation, so unusual required types don't block it
            values = {n: overrides.get(n, example_value(hints.get(n, f.annotation), depth))
                      for n, f in fields.items() if n in overrides or f.is_required()}
            return cls.model_construct(**values)
        if typing.is_typeddict(cls):
            required = getattr(cls, "__required_keys__", set(hints))
            return {n: overrides.get(n, example_value(t, depth)) for n, t in hints.items() if n in required or n in overrides}
        return cls(**overrides) if overrides else cls()
    except Exception:  # noqa: BLE001 - a context we can't build: the agent runs without one, as before
        return None


def schema_fields(cls: Any) -> dict[str, Any]:
    """field -> annotation for a dataclass, pydantic model or TypedDict."""
    import dataclasses
    import typing
    try:
        hints = typing.get_type_hints(cls, include_extras=True)
    except Exception:  # noqa: BLE001
        hints = getattr(cls, "__annotations__", {}) or {}
    if dataclasses.is_dataclass(cls):
        return {f.name: hints.get(f.name, f.type) for f in dataclasses.fields(cls)}
    if getattr(cls, "model_fields", None) is not None:
        return {n: hints.get(n, f.annotation) for n, f in cls.model_fields.items()}
    return dict(hints)
