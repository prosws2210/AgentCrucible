"""The two gateways that make AgentCrucible framework-agnostic.

Every agent, whatever it is built with, does two things: calls an LLM API and calls tools.
Point its OpenAI-compatible base URL at the LLM gateway and its MCP server URLs at the MCP
gateway, and every model call and tool call is recorded (and can be cached, replayed,
mocked, blocked or injected) without touching the agent's code.

Routes (one HTTP server per run, episodes are isolated by path):
    /ep/{episode_id}/v1/chat/completions      OpenAI-compatible LLM proxy
    /ep/{episode_id}/v1/models
    /ep/{episode_id}/mcp/{server}             MCP Streamable HTTP proxy -> per-episode stdio server
"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import socket
import sys
import time
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
import mcp.types as mt
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .config import Environment, LLMSettings, McpServerSpec
from .trajectory import Recorder, clip


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def split_command(command: str) -> list[str]:
    """Split a command line; a leading `python` means the interpreter running AgentCrucible."""
    parts = shlex.split(command, posix=True)
    if parts and parts[0] in ("python", "python3"):
        parts[0] = sys.executable
    return parts


def content_text(blocks: list[Any]) -> str:
    out = []
    for b in blocks:
        out.append(b.text if getattr(b, "type", None) == "text" else f"[{getattr(b, 'type', 'content')}]")
    return "\n".join(out)


# ------------------------------------------------------------------ MCP proxy


class McpProxy:
    """Spawns one real MCP server (stdio) for an episode and exposes it over Streamable HTTP."""

    def __init__(self, name: str, spec: McpServerSpec, env: dict[str, str], rec: Recorder,
                 environment: Environment, root: Path):
        self.name, self.spec, self.env, self.rec, self.environment, self.root = name, spec, env, rec, environment, root
        self.tools: list[mt.Tool] = []
        self.manager: StreamableHTTPSessionManager | None = None
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "McpProxy":
        cmd = split_command(self.spec.command)
        cwd = self.spec.cwd and str((self.root / self.spec.cwd).resolve())
        params = StdioServerParameters(
            command=cmd[0], args=cmd[1:], cwd=cwd or str(self.root),
            env={**os.environ, **self.spec.env, **self.env},
        )
        read, write = await self._stack.enter_async_context(stdio_client(params, errlog=open(os.devnull, "w")))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()
        self.tools = (await self.session.list_tools()).tools

        server: Server = Server(f"crucible-proxy-{self.name}")

        @server.list_tools()
        async def _list() -> list[mt.Tool]:
            return self.tools

        @server.call_tool(validate_input=False)
        async def _call(tool: str, args: dict[str, Any]) -> mt.CallToolResult:
            return await self._handle_call(tool, args or {})

        self.manager = StreamableHTTPSessionManager(app=server, stateless=True, json_response=True)
        await self._stack.enter_async_context(self.manager.run())
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self._stack.aclose()

    async def _handle_call(self, tool: str, args: dict[str, Any]) -> mt.CallToolResult:
        env = self.environment
        start = time.monotonic()
        call = self.rec.add("tool_call", server=self.name, tool=tool, args=args)
        if tool in env.deny_tools:
            call["blocked"] = True
            return self._result(tool, f"Tool '{tool}' is blocked by test policy.", True, start)
        if tool in env.mocks:
            call["mocked"] = True
            mock = env.mocks[tool]
            return self._result(tool, mock if isinstance(mock, str) else json.dumps(mock), False, start)
        try:
            res = await self.session.call_tool(tool, args)
        except Exception as e:  # server crashed or protocol error
            return self._result(tool, f"MCP error: {e}", True, start)
        content = list(res.content)
        if tool in env.inject:
            content.append(mt.TextContent(type="text", text=env.inject[tool]))
            call["injected"] = True
        text = content_text(content)
        self.rec.add("tool_result", server=self.name, tool=tool, is_error=bool(res.isError),
                     content=clip(text), latency_ms=round((time.monotonic() - start) * 1000, 1))
        return mt.CallToolResult(content=content, structuredContent=res.structuredContent, isError=res.isError)

    def _result(self, tool: str, text: str, is_error: bool, start: float) -> mt.CallToolResult:
        self.rec.add("tool_result", server=self.name, tool=tool, is_error=is_error, content=clip(text),
                     latency_ms=round((time.monotonic() - start) * 1000, 1))
        return mt.CallToolResult(content=[mt.TextContent(type="text", text=text)], isError=is_error)


# ------------------------------------------------------------------ LLM proxy + router


@dataclass
class EpisodeRoutes:
    rec: Recorder
    proxies: dict[str, McpProxy] = field(default_factory=dict)


class Gateway:
    """ASGI app routing /ep/{id}/... to the right episode."""

    def __init__(self, llm: LLMSettings, cache_dir: Path, force_model: str | None = None):
        self.llm = llm
        self.cache_dir = cache_dir
        self.force_model = force_model
        self.episodes: dict[str, EpisodeRoutes] = {}
        self.client = httpx.AsyncClient(timeout=httpx.Timeout(600.0))
        self.port = free_port()

    def base(self, episode_id: str) -> str:
        return f"http://127.0.0.1:{self.port}/ep/{episode_id}"

    # ASGI entrypoint -------------------------------------------------
    async def __call__(self, scope: dict, receive: Any, send: Any) -> None:
        if scope["type"] == "lifespan":
            while True:
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif msg["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        parts = scope["path"].strip("/").split("/")
        if len(parts) < 3 or parts[0] != "ep" or parts[1] not in self.episodes:
            return await JSONResponse({"error": "unknown episode"}, 404)(scope, receive, send)
        ep = self.episodes[parts[1]]
        if parts[2] == "mcp" and len(parts) >= 4 and parts[3] in ep.proxies:
            mgr = ep.proxies[parts[3]].manager
            assert mgr is not None
            return await mgr.handle_request(scope, receive, send)
        if parts[2] == "v1":
            req = Request(scope, receive)
            tail = "/".join(parts[3:])
            if tail == "chat/completions" and req.method == "POST":
                resp = await self._chat(ep, await req.json())
            elif tail == "models":
                resp = JSONResponse({"object": "list", "data": [{"id": self.force_model or "model", "object": "model"}]})
            else:
                resp = JSONResponse({"error": f"unsupported endpoint {tail}"}, 404)
            return await resp(scope, receive, send)
        return await JSONResponse({"error": "not found"}, 404)(scope, receive, send)

    # chat completions --------------------------------------------------
    async def _chat(self, ep: EpisodeRoutes, body: dict[str, Any]) -> Response:
        rec = ep.rec
        stream = bool(body.pop("stream", False))
        body.pop("stream_options", None)
        if self.force_model:
            body["model"] = self.force_model
        key = hashlib.sha256(json.dumps(
            {"scenario": rec.scenario_id, "attempt": rec.attempt, "body": body}, sort_keys=True, default=str
        ).encode()).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        start = time.monotonic()
        cache_state = "off"
        data: dict[str, Any] | None = None
        if self.llm.cache in ("read_write", "replay") and cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            cache_state = "hit"
        elif self.llm.cache == "replay":
            rec.add("llm_call", model=body.get("model"), error="replay cache miss")
            return JSONResponse({"error": {"message": "agentcrucible replay: no cached response"}}, 409)
        if data is None:
            try:
                r = await self.client.post(
                    self.llm.upstream_base_url.rstrip("/") + "/chat/completions", json=body,
                    headers={"Authorization": f"Bearer {self.llm.api_key}"},
                )
            except httpx.HTTPError as e:
                rec.add("llm_call", model=body.get("model"), error=f"upstream unreachable: {e}")
                return JSONResponse({"error": {"message": str(e)}}, 502)
            if r.status_code != 200:
                rec.add("llm_call", model=body.get("model"), error=f"upstream {r.status_code}: {clip(r.text, 300)}")
                return Response(r.content, r.status_code, media_type="application/json")
            data = r.json()
            if self.llm.cache == "read_write":
                cache_file.parent.mkdir(parents=True, exist_ok=True)
                cache_file.write_text(json.dumps(data), encoding="utf-8")
                cache_state = "miss"
        self._record(rec, body, data, start, cache_state)
        if stream:
            return StreamingResponse(_as_sse(data), media_type="text/event-stream")
        return JSONResponse(data)

    def _record(self, rec: Recorder, body: dict, data: dict, start: float, cache_state: str) -> None:
        usage = data.get("usage") or {}
        tin, tout = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
        choice = (data.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        rec.add(
            "llm_call",
            model=data.get("model") or body.get("model"),
            tokens_in=tin, tokens_out=tout,
            cost_usd=round(tin / 1000 * self.llm.price_per_1k_input + tout / 1000 * self.llm.price_per_1k_output, 6),
            latency_ms=round((time.monotonic() - start) * 1000, 1),
            cache=cache_state,
            finish_reason=choice.get("finish_reason"),
            n_messages=len(body.get("messages", [])),
            n_tools=len(body.get("tools") or []),
            content=clip(msg.get("content") or ""),
            tool_calls=[(tc.get("function") or {}).get("name") for tc in msg.get("tool_calls") or []],
        )


def _as_sse(data: dict[str, Any]):
    """Turn a complete chat.completion into a minimal valid SSE stream."""
    choice = (data.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    delta: dict[str, Any] = {"role": "assistant", "content": msg.get("content") or ""}
    if msg.get("tool_calls"):
        delta["tool_calls"] = [{**tc, "index": i} for i, tc in enumerate(msg["tool_calls"])]
    base = {"id": data.get("id", "chatcmpl-crucible"), "object": "chat.completion.chunk",
            "created": data.get("created", int(time.time())), "model": data.get("model", "")}
    yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': delta, 'finish_reason': None}]})}\n\n"
    yield f"data: {json.dumps({**base, 'choices': [{'index': 0, 'delta': {}, 'finish_reason': choice.get('finish_reason', 'stop')}], 'usage': data.get('usage')})}\n\n"
    yield "data: [DONE]\n\n"
