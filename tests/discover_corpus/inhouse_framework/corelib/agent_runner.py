"""Minimal in-house agent runtime used by internal finance tooling."""
import inspect
import json
import logging
from typing import Any, Callable, get_type_hints

import openai  # noqa: F401  (kept for type references / error classes)

log = logging.getLogger("corelib.agent")

_PY_TO_JSON = {str: "string", int: "integer", float: "number", bool: "boolean", list: "array", dict: "object"}


def _schema_for(fn: Callable) -> dict:
    hints = get_type_hints(fn)
    sig = inspect.signature(fn)
    props, required = {}, []
    for pname, param in sig.parameters.items():
        props[pname] = {"type": _PY_TO_JSON.get(hints.get(pname, str), "string")}
        if param.default is inspect.Parameter.empty:
            required.append(pname)
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip(),
            "parameters": {"type": "object", "properties": props, "required": required},
        },
    }


class AgentRunner:
    def __init__(self, llm, tools: list[Callable], system_prompt: str = "", max_steps: int = 6):
        self.llm = llm
        self.tools = {fn.__name__: fn for fn in tools}
        self.tool_specs = [_schema_for(fn) for fn in tools]
        self.system_prompt = system_prompt
        self.max_steps = max_steps

    def run(self, user_input: str) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_input},
        ]
        for _ in range(self.max_steps):
            msg = self.llm.complete(messages, tools=self.tool_specs)
            if not msg.tool_calls:
                return msg.content or ""
            messages.append(msg.model_dump(exclude_none=True))
            for tc in msg.tool_calls:
                fn = self.tools[tc.function.name]
                try:
                    result = fn(**json.loads(tc.function.arguments))
                except Exception as exc:
                    log.warning("tool %s raised %s", tc.function.name, exc)
                    result = {"error": str(exc)}
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": json.dumps(result, default=str)})
        return "step limit reached"
