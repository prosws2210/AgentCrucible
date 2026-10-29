"""Serve a CrewAI `Crew` (or a `@CrewBase` class / a function returning a crew).

Each turn calls `crew.kickoff(inputs=...)` with the user's message under the input names your tasks use. By default
the message is offered as `input`, `query`, `question`, `topic`, `message` and `request`; pass `input_keys` to choose.
"""

from __future__ import annotations

from typing import Any

from . import History, as_text
from . import serve as _serve

DEFAULT_KEYS = ("input", "query", "question", "topic", "message", "request")


def _crew(obj: Any) -> Any:
    if hasattr(obj, "kickoff"):
        return obj
    if isinstance(obj, type):  # @CrewBase class
        inst = obj()
        return inst.crew() if hasattr(inst, "crew") else inst
    return obj()


def turn_for(crew_or_factory: Any, input_keys: tuple[str, ...] = DEFAULT_KEYS):
    def turn(history: History) -> str:
        crew = _crew(crew_or_factory)  # fresh crew per turn: kickoff mutates task state
        text = history[-1]["content"]
        earlier = "\n".join(f"{m['role']}: {m['content']}" for m in history[:-1])
        inputs = {k: text for k in input_keys}
        if earlier:
            inputs["history"] = earlier
        return as_text(crew.kickoff(inputs=inputs))

    return turn


def serve(crew_or_factory: Any, input_keys: tuple[str, ...] = DEFAULT_KEYS) -> None:
    _serve(turn_for(crew_or_factory, input_keys))
