"""Turn recorded production conversations into draft scenarios (plan, Phase 3).

Understands:
  * OpenTelemetry (OTLP JSON export) with GenAI semantic conventions, including OpenInference / OpenLLMetry attributes
  * LangSmith run exports (a JSON list, or JSONL, of runs with run_type / trace_id / inputs / outputs)
  * plain JSONL conversations: {"messages": [{"role", "content"}], "tools": ["name", ...]}
Each conversation becomes a scenario whose task is the user's first message, with soft checks for the tools that were
called in production. Review them: production behaviour isn't automatically correct behaviour.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from .scan import redact
from .schema import DraftScenario


def _attrs(span: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for a in span.get("attributes") or []:
        v = a.get("value") or {}
        out[a.get("key", "")] = next((v[k] for k in ("stringValue", "intValue", "doubleValue", "boolValue") if k in v), None)
    return out


def _user_text(value: Any) -> str | None:
    """First user message from the many shapes traces use."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return value if value.strip() else None
    if isinstance(value, dict):
        for k in ("input", "question", "query", "prompt", "message", "user_input", "content", "text"):
            if isinstance(value.get(k), str):
                return value[k]
        if "messages" in value:
            return _user_text(value["messages"])
    if isinstance(value, list):
        for m in value:
            if isinstance(m, list):  # LangSmith nests [[messages]]
                t = _user_text(m)
                if t:
                    return t
            if isinstance(m, dict) and m.get("role") in ("user", "human") or (isinstance(m, dict) and m.get("type") == "human"):
                c = m.get("content") or (m.get("data") or {}).get("content")
                if isinstance(c, str):
                    return c
                if isinstance(c, list):
                    return " ".join(p.get("text", "") for p in c if isinstance(p, dict)) or None
                parts = m.get("parts")
                if isinstance(parts, list):
                    return " ".join(p.get("content", "") for p in parts if isinstance(p, dict)) or None
    return None


_INDEXED = re.compile(r"^(llm\.input_messages|gen_ai\.prompt)\.(\d+)\.(?:message\.)?(role|content)$")


def _indexed_user_message(attrs: dict[str, Any]) -> str | None:
    """OpenInference (llm.input_messages.N.message.*) and OpenLLMetry (gen_ai.prompt.N.*): the first user message."""
    msgs: dict[tuple[str, int], dict[str, Any]] = {}
    for key, value in attrs.items():
        m = _INDEXED.match(key)
        if m:
            msgs.setdefault((m.group(1), int(m.group(2))), {})[m.group(3)] = value
    for _, msg in sorted(msgs.items()):
        if msg.get("role") in ("user", "human") and isinstance(msg.get("content"), str) and msg["content"].strip():
            return msg["content"]
    return None


def _otel(data: dict[str, Any]) -> list[dict[str, Any]]:
    traces: dict[str, dict[str, Any]] = {}
    for rs in data.get("resourceSpans") or []:
        for ss in rs.get("scopeSpans") or rs.get("instrumentationLibrarySpans") or []:
            for span in ss.get("spans") or []:
                a = _attrs(span)
                t = traces.setdefault(span.get("traceId", "?"), {"input": None, "tools": [], "start": span.get("startTimeUnixNano", 0)})
                tool = a.get("gen_ai.tool.name") or a.get("tool.name")
                if tool or str(span.get("name", "")).startswith("execute_tool"):
                    t["tools"].append(tool or str(span["name"]).removeprefix("execute_tool ").strip())
                if t["input"] is None:
                    t["input"] = _indexed_user_message(a)
                if t["input"] is None:
                    for key in ("gen_ai.input.messages", "gen_ai.prompt", "input.value", "traceloop.entity.input"):
                        if a.get(key):
                            t["input"] = _user_text(a[key])
                            if t["input"]:
                                break
    return [{"input": t["input"], "tools": t["tools"], "id": tid} for tid, t in sorted(traces.items(), key=lambda kv: kv[1]["start"]) if t["input"]]


def _langsmith(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    traces: dict[str, dict[str, Any]] = {}
    for r in runs:
        tid = str(r.get("trace_id") or r.get("id"))
        t = traces.setdefault(tid, {"input": None, "tools": [], "id": tid})
        if r.get("run_type") == "tool":
            t["tools"].append(r.get("name"))
        if not r.get("parent_run_id") and t["input"] is None:
            t["input"] = _user_text(r.get("inputs"))
    for r in runs:  # fall back to the first LLM input of a trace
        t = traces[str(r.get("trace_id") or r.get("id"))]
        if t["input"] is None and r.get("run_type") == "llm":
            t["input"] = _user_text(r.get("inputs"))
    return [t for t in traces.values() if t["input"]]


def read_traces(path: Path) -> list[dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    rows: list[Any]
    try:
        data = json.loads(text)
        rows = data if isinstance(data, list) else [data]
    except json.JSONDecodeError:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    out: list[dict[str, Any]] = []
    if rows and isinstance(rows[0], dict) and "resourceSpans" in rows[0]:
        for r in rows:
            out += _otel(r)
    elif rows and isinstance(rows[0], dict) and ("run_type" in rows[0] or "trace_id" in rows[0]):
        out = _langsmith(rows)
    else:
        for i, r in enumerate(rows):
            if not isinstance(r, dict):
                continue
            text_in = _user_text(r.get("messages")) or _user_text(r)
            if text_in:
                out.append({"input": text_in, "tools": list(r.get("tools") or r.get("tools_called") or []), "id": str(r.get("id", i))})
    return out


def to_scenarios(traces: list[dict[str, Any]], agent: str | None = None, prefix: str = "trace", limit: int = 50) -> list[DraftScenario]:
    out: list[DraftScenario] = []
    seen: set[str] = set()
    for t in traces[:limit]:
        task = redact(" ".join(str(t["input"]).split()))[:1000]
        key = task.lower()[:200]
        if key in seen:
            continue
        seen.add(key)
        tools = list(dict.fromkeys(x for x in t["tools"] if x))
        sid = f"{prefix}-{len(out) + 1}-" + (re.sub(r"[^a-z0-9]+", "-", task.lower())[:40].strip("-") or "conversation")
        checks: list[Any] = [{"trajectory.tool_called": {"tool": x, "hard": False}} for x in tools[:6]]
        checks.append({"budget.max_llm_calls": {"max": 20, "hard": False}})
        sc: dict[str, Any] = {"id": sid, "description": f"Imported from a production trace ({t['id']}). Review the checks: "
                                                       "they record what happened, not what should happen."}
        if agent:
            sc["agent"] = agent
        sc.update(task=task, checks=checks)
        out.append(DraftScenario(id=sid, agent=agent or "", reason="Imported from a production trace.",
                                 yaml=yaml.safe_dump(sc, sort_keys=False, allow_unicode=True, width=110)))
    return out
