"""Wire formats the LLM gateway understands: OpenAI Chat Completions, OpenAI Responses and Anthropic Messages.

For each API this module knows how to
  * summarize a complete response for the trajectory (tokens, text, tool calls, stop reason)
  * rebuild a complete response from a streamed one (so streams are recorded and cached like any call)
  * replay a cached complete response as a valid stream
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Iterator, Literal

Api = Literal["openai", "anthropic", "responses"]


@dataclass
class Summary:
    model: str | None
    tokens_in: int
    tokens_out: int
    content: str
    tool_calls: list[str]
    stop_reason: str | None
    # the tools the model asked for, with arguments: how in-process tools (not MCP) become visible
    tool_requests: list[dict[str, Any]] = field(default_factory=list)


def _args(raw: Any) -> Any:
    if isinstance(raw, str):
        try:
            return json.loads(raw) if raw.strip() else {}
        except json.JSONDecodeError:
            return {"_raw": raw}
    return raw if raw is not None else {}


def summarize(api: Api, data: dict[str, Any]) -> Summary:
    if api == "responses":
        usage = data.get("usage") or {}
        items = data.get("output") or []
        text = "".join(c.get("text", "") for it in items if it.get("type") == "message"
                       for c in it.get("content") or [] if c.get("type") == "output_text")
        return Summary(
            model=data.get("model"),
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            content=text,
            tool_calls=[it.get("name", "") for it in items if it.get("type") == "function_call"],
            stop_reason=data.get("status"),
            tool_requests=[{"name": it.get("name", ""), "args": _args(it.get("arguments"))}
                           for it in items if it.get("type") == "function_call"],
        )
    if api == "anthropic":
        usage = data.get("usage") or {}
        blocks = data.get("content") or []
        return Summary(
            model=data.get("model"),
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            content="".join(b.get("text", "") for b in blocks if b.get("type") == "text"),
            tool_calls=[b.get("name", "") for b in blocks if b.get("type") == "tool_use"],
            stop_reason=data.get("stop_reason"),
            tool_requests=[{"name": b.get("name", ""), "args": _args(b.get("input"))}
                           for b in blocks if b.get("type") == "tool_use"],
        )
    usage = data.get("usage") or {}
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    return Summary(
        model=data.get("model"),
        tokens_in=int(usage.get("prompt_tokens") or 0),
        tokens_out=int(usage.get("completion_tokens") or 0),
        content=msg.get("content") or "",
        tool_calls=[(tc.get("function") or {}).get("name", "") for tc in msg.get("tool_calls") or []],
        stop_reason=choice.get("finish_reason"),
        tool_requests=[{"name": (tc.get("function") or {}).get("name", ""), "args": _args((tc.get("function") or {}).get("arguments"))}
                       for tc in msg.get("tool_calls") or []],
    )


# ------------------------------------------------------------------ stream accumulators


def _sse_json(line: bytes) -> dict[str, Any] | None:
    line = line.strip()
    if not line.startswith(b"data:"):
        return None
    payload = line[5:].strip()
    if not payload or payload == b"[DONE]":
        return None
    try:
        return json.loads(payload)
    except json.JSONDecodeError:
        return None


@dataclass
class OpenAIStream:
    meta: dict[str, Any] = field(default_factory=dict)
    content: list[str] = field(default_factory=list)
    tools: dict[int, dict[str, Any]] = field(default_factory=dict)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None

    def feed(self, line: bytes) -> None:
        ev = _sse_json(line)
        if ev is None:
            return
        for k in ("id", "model", "created"):
            if k in ev:
                self.meta.setdefault(k, ev[k])
        if ev.get("usage"):
            self.usage = ev["usage"]
        for ch in ev.get("choices") or []:
            delta = ch.get("delta") or {}
            if delta.get("content"):
                self.content.append(delta["content"])
            for tc in delta.get("tool_calls") or []:
                slot = self.tools.setdefault(tc.get("index", 0), {"id": "", "type": "function",
                                                                   "function": {"name": "", "arguments": ""}})
                if tc.get("id"):
                    slot["id"] = tc["id"]
                fn = tc.get("function") or {}
                slot["function"]["name"] += fn.get("name") or ""
                slot["function"]["arguments"] += fn.get("arguments") or ""
            if ch.get("finish_reason"):
                self.finish_reason = ch["finish_reason"]

    def result(self) -> dict[str, Any]:
        msg: dict[str, Any] = {"role": "assistant", "content": "".join(self.content) or None}
        if self.tools:
            msg["tool_calls"] = [self.tools[i] for i in sorted(self.tools)]
        return {"id": self.meta.get("id", "chatcmpl-crucible"), "object": "chat.completion",
                "created": self.meta.get("created", int(time.time())), "model": self.meta.get("model", ""),
                "choices": [{"index": 0, "message": msg, "finish_reason": self.finish_reason or "stop"}],
                "usage": self.usage or {}}


@dataclass
class AnthropicStream:
    message: dict[str, Any] = field(default_factory=dict)
    blocks: dict[int, dict[str, Any]] = field(default_factory=dict)
    partial_json: dict[int, str] = field(default_factory=dict)
    stop_reason: str | None = None
    output_tokens: int = 0

    def feed(self, line: bytes) -> None:
        ev = _sse_json(line)
        if ev is None:
            return
        t = ev.get("type")
        if t == "message_start":
            self.message = dict(ev.get("message") or {})
        elif t == "content_block_start":
            self.blocks[ev["index"]] = dict(ev.get("content_block") or {})
        elif t == "content_block_delta":
            d = ev.get("delta") or {}
            blk = self.blocks.setdefault(ev["index"], {"type": "text", "text": ""})
            if d.get("type") == "text_delta":
                blk["text"] = blk.get("text", "") + d.get("text", "")
            elif d.get("type") == "input_json_delta":
                self.partial_json[ev["index"]] = self.partial_json.get(ev["index"], "") + d.get("partial_json", "")
        elif t == "message_delta":
            d = ev.get("delta") or {}
            self.stop_reason = d.get("stop_reason") or self.stop_reason
            self.output_tokens = int((ev.get("usage") or {}).get("output_tokens") or self.output_tokens)

    def result(self) -> dict[str, Any]:
        content = []
        for i in sorted(self.blocks):
            blk = dict(self.blocks[i])
            if blk.get("type") == "tool_use":
                raw = self.partial_json.get(i, "")
                try:
                    blk["input"] = json.loads(raw) if raw else (blk.get("input") or {})
                except json.JSONDecodeError:
                    blk["input"] = {"_unparsed": raw}
            content.append(blk)
        usage = dict(self.message.get("usage") or {})
        usage["output_tokens"] = self.output_tokens or usage.get("output_tokens", 0)
        return {**self.message, "type": "message", "role": "assistant", "content": content,
                "stop_reason": self.stop_reason, "usage": usage}


@dataclass
class ResponsesStream:
    """OpenAI Responses stream: the final `response.completed` event carries the whole response."""

    final: dict[str, Any] | None = None
    meta: dict[str, Any] = field(default_factory=dict)
    items: dict[int, dict[str, Any]] = field(default_factory=dict)

    def feed(self, line: bytes) -> None:
        ev = _sse_json(line)
        if ev is None:
            return
        t = ev.get("type", "")
        if t in ("response.completed", "response.incomplete", "response.failed"):
            self.final = ev.get("response")
        elif t == "response.created":
            self.meta = dict(ev.get("response") or {})
        elif t == "response.output_item.done":
            self.items[ev.get("output_index", len(self.items))] = ev.get("item") or {}

    def result(self) -> dict[str, Any]:
        if self.final:
            return self.final
        return {**self.meta, "status": "incomplete", "output": [self.items[i] for i in sorted(self.items)]}


def accumulator(api: Api) -> OpenAIStream | AnthropicStream | ResponsesStream:
    if api == "responses":
        return ResponsesStream()
    return AnthropicStream() if api == "anthropic" else OpenAIStream()


# ------------------------------------------------------------------ replay a complete response as a stream


def as_sse(api: Api, data: dict[str, Any]) -> Iterator[str]:
    if api == "responses":
        yield from _responses_sse(data)
        return
    if api == "anthropic":
        yield from _anthropic_sse(data)
    else:
        yield from _openai_sse(data)


def _openai_sse(data: dict[str, Any]) -> Iterator[str]:
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    delta: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        delta["tool_calls"] = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
    base = {"id": data.get("id", "chatcmpl-crucible"), "object": "chat.completion.chunk",
            "created": data.get("created", int(time.time())), "model": data.get("model", "")}
    yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]})}\n\n"
    end = {**base, "choices": [{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason", "stop")}],
           "usage": data.get("usage")}
    yield f"data: {json.dumps(end)}\n\n"
    yield "data: [DONE]\n\n"


def _anthropic_sse(data: dict[str, Any]) -> Iterator[str]:
    def ev(name: str, payload: dict[str, Any]) -> str:
        return f"event: {name}\ndata: {json.dumps(payload)}\n\n"

    usage = data.get("usage") or {}
    start = {k: v for k, v in data.items() if k not in ("content", "stop_reason", "usage")}
    start.update({"content": [], "stop_reason": None,
                  "usage": {"input_tokens": usage.get("input_tokens", 0), "output_tokens": 0}})
    yield ev("message_start", {"type": "message_start", "message": start})
    for i, blk in enumerate(data.get("content") or []):
        if blk.get("type") == "tool_use":
            yield ev("content_block_start", {"type": "content_block_start", "index": i,
                                             "content_block": {**blk, "input": {}}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                             "delta": {"type": "input_json_delta",
                                                       "partial_json": json.dumps(blk.get("input") or {})}})
        else:
            yield ev("content_block_start", {"type": "content_block_start", "index": i,
                                             "content_block": {"type": "text", "text": ""}})
            yield ev("content_block_delta", {"type": "content_block_delta", "index": i,
                                             "delta": {"type": "text_delta", "text": blk.get("text", "")}})
        yield ev("content_block_stop", {"type": "content_block_stop", "index": i})
    yield ev("message_delta", {"type": "message_delta", "delta": {"stop_reason": data.get("stop_reason")},
                               "usage": {"output_tokens": usage.get("output_tokens", 0)}})
    yield ev("message_stop", {"type": "message_stop"})


def _responses_sse(data: dict[str, Any]) -> Iterator[str]:
    seq = 0

    def ev(payload: dict[str, Any]) -> str:
        nonlocal seq
        payload = {**payload, "sequence_number": seq}
        seq += 1
        return f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n"

    yield ev({"type": "response.created", "response": {**data, "status": "in_progress", "output": []}})
    yield ev({"type": "response.in_progress", "response": {**data, "status": "in_progress", "output": []}})
    for i, item in enumerate(data.get("output") or []):
        iid = item.get("id", f"item_{i}")
        if item.get("type") == "message":
            yield ev({"type": "response.output_item.added", "output_index": i, "item": {**item, "content": [], "status": "in_progress"}})
            for j, part in enumerate(item.get("content") or []):
                text = part.get("text", "")
                yield ev({"type": "response.content_part.added", "item_id": iid, "output_index": i, "content_index": j,
                          "part": {**part, "text": ""}})
                yield ev({"type": "response.output_text.delta", "item_id": iid, "output_index": i, "content_index": j,
                          "delta": text, "logprobs": []})
                yield ev({"type": "response.output_text.done", "item_id": iid, "output_index": i, "content_index": j,
                          "text": text, "logprobs": []})
                yield ev({"type": "response.content_part.done", "item_id": iid, "output_index": i, "content_index": j, "part": part})
        elif item.get("type") == "function_call":
            yield ev({"type": "response.output_item.added", "output_index": i,
                      "item": {**item, "arguments": "", "status": "in_progress"}})
            yield ev({"type": "response.function_call_arguments.delta", "item_id": iid, "output_index": i,
                      "delta": item.get("arguments", "")})
            yield ev({"type": "response.function_call_arguments.done", "item_id": iid, "output_index": i,
                      "arguments": item.get("arguments", "")})
        else:
            yield ev({"type": "response.output_item.added", "output_index": i, "item": item})
        yield ev({"type": "response.output_item.done", "output_index": i, "item": item})
    yield ev({"type": "response.completed", "response": data})
