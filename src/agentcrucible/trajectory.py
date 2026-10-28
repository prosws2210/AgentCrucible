"""Trajectory recording: an ordered list of timestamped events for one episode."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

MAX_TEXT = 4000


def clip(value: Any, limit: int = MAX_TEXT) -> Any:
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + f"... [{len(value) - limit} chars truncated]"
    return value


@dataclass
class Recorder:
    episode_id: str
    scenario_id: str
    attempt: int
    t0: float = field(default_factory=time.monotonic)
    events: list[dict[str, Any]] = field(default_factory=list)
    turn: int = 0

    def add(self, type_: str, **data: Any) -> dict[str, Any]:
        ev = {"t": round(time.monotonic() - self.t0, 3), "type": type_, "turn": self.turn, **data}
        self.events.append(ev)
        return ev

    # convenience views used by graders and reports -------------------

    def of(self, *types: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e["type"] in types]

    @property
    def tool_calls(self) -> list[dict[str, Any]]:
        return self.of("tool_call")

    @property
    def final_reply(self) -> str:
        msgs = self.of("assistant_message")
        return msgs[-1]["content"] if msgs else ""

    @property
    def transcript(self) -> str:
        lines = []
        for e in self.events:
            if e["type"] == "user_message":
                lines.append(f"USER: {e['content']}")
            elif e["type"] == "assistant_message":
                lines.append(f"AGENT: {e['content']}")
            elif e["type"] == "tool_call":
                lines.append(f"[tool call] {e['tool']}({json.dumps(e.get('args', {}))})")
            elif e["type"] == "tool_result":
                lines.append(f"[tool result] {clip(str(e.get('content', '')), 500)}")
        return "\n".join(lines)

    def totals(self) -> dict[str, Any]:
        llm = self.of("llm_call")
        return {
            "llm_calls": len(llm),
            "tokens_in": sum(e.get("tokens_in", 0) for e in llm),
            "tokens_out": sum(e.get("tokens_out", 0) for e in llm),
            "cost_usd": round(sum(e.get("cost_usd", 0.0) for e in llm), 6),
            "tool_calls": len(self.tool_calls),
            "turns": self.turn,
            "duration_s": self.events[-1]["t"] if self.events else 0.0,
        }

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for e in self.events:
                f.write(json.dumps(e, default=str) + "\n")


def load_events(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
