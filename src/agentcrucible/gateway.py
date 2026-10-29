"""The two gateways that make AgentCrucible framework-agnostic.

Every agent, whatever it is built with, does two things: calls an LLM API and calls tools.
Point its OpenAI-compatible base URL at the LLM gateway and its MCP server URLs at the MCP
gateway, and every model call and tool call is recorded (and can be cached, replayed,
mocked, blocked or injected) without touching the agent's code.

Routes (one HTTP server per run, episodes are isolated by path):
    /ep/{episode_id}/v1/chat/completions      OpenAI Chat Completions proxy (streaming supported)
    /ep/{episode_id}/v1/messages              Anthropic Messages proxy (streaming supported)
    /ep/{episode_id}/v1/responses             OpenAI Responses proxy (streaming supported)
    /ep/{episode_id}/http/{name}/...          HTTP mock declared in the scenario (requests recorded)
    /ep/{episode_id}/v1/models
    /ep/{episode_id}/mcp/{server}             MCP Streamable HTTP proxy -> per-episode stdio server
"""

from __future__ import annotations

import contextlib
import fnmatch
import hashlib
import json
import os
import shlex
import shutil
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
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse

from .config import Environment, LLMSettings, McpServerSpec, MockRoute
from .llm import Api, accumulator, as_sse, summarize
from .snapshot import answer as snapshot_answer
from .snapshot import is_snapshot_mock
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
    elif parts and os.name == "nt" and not any(c in parts[0] for c in "/\\"):
        # Windows can't start `npx`, `go` or `mvn` by bare name when they are .cmd/.exe files found through PATH
        parts[0] = shutil.which(parts[0]) or parts[0]
    return parts


def content_text(blocks: list[Any]) -> str:
    out = []
    for b in blocks:
        out.append(b.text if getattr(b, "type", None) == "text" else f"[{getattr(b, 'type', 'content')}]")
    return "\n".join(out)


# ------------------------------------------------------------------ MCP proxy


async def probe_remote(name: str, spec: McpServerSpec, timeout: float = 15) -> None:
    """Fail fast with a readable error when a remote MCP server is down or rejects our headers.

    The MCP client reports HTTP errors by cancelling its task group, which surfaces as a bare CancelledError.
    """
    url = spec.url or ""
    try:
        async with httpx.AsyncClient(timeout=timeout, headers=spec.headers) as client:
            if spec.transport == "sse":
                async with client.stream("GET", url, headers={"Accept": "text/event-stream"}) as r:
                    status = r.status_code
            else:
                r = await client.post(url, headers={"Accept": "application/json, text/event-stream"}, json={
                    "jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {
                        "protocolVersion": mt.LATEST_PROTOCOL_VERSION, "capabilities": {},
                        "clientInfo": {"name": "agentcrucible-probe", "version": "1"}}})
                status = r.status_code
                if sid := r.headers.get("mcp-session-id"):  # don't leave the probe's session open
                    with contextlib.suppress(httpx.HTTPError):
                        await client.delete(url, headers={"mcp-session-id": sid})
    except httpx.HTTPError as e:
        raise ConnectionError(f"MCP server {name!r} at {url} is unreachable: {type(e).__name__}: {e}") from None
    if status in (401, 403):
        raise PermissionError(f"MCP server {name!r} at {url} returned HTTP {status}: check its `headers` in crucible.yaml")
    if status >= 400:
        raise ConnectionError(f"MCP server {name!r} at {url} returned HTTP {status}")


class McpProxy:
    """Spawns one real MCP server (stdio) for an episode and exposes it over Streamable HTTP."""

    def __init__(self, name: str, spec: McpServerSpec, env: dict[str, str], rec: Recorder,
                 environment: Environment, root: Path):
        self.name, self.spec, self.env, self.rec, self.environment, self.root = name, spec, env, rec, environment, root
        self.tools: list[mt.Tool] = []
        self.manager: StreamableHTTPSessionManager | None = None
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> "McpProxy":
        if self.spec.url:  # already-running remote server
            await probe_remote(self.name, self.spec)
            if self.spec.transport == "sse":
                read, write = await self._stack.enter_async_context(sse_client(self.spec.url, headers=self.spec.headers))
            else:
                read, write, _ = await self._stack.enter_async_context(
                    streamablehttp_client(self.spec.url, headers=self.spec.headers))
        else:  # local server, started fresh for this episode
            cmd = split_command(self.spec.command or "")
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
            if is_snapshot_mock(mock):  # a retriever answered from the document snapshot
                mock = snapshot_answer(mock, args)
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
    http_mocks: dict[str, list[MockRoute]] = field(default_factory=dict)
    llm_n: int = 0  # LLM calls made so far in this episode
    llm_seq: list[dict[str, str]] = field(default_factory=list)  # cache keys in call order (read_write)
    requested_model: str | None = None  # the model named in the latest call, before --model overrides it
    model: str | None = None  # this episode's agent forces its own model (agents.<name>.model)
    model_map: dict[str, str] = field(default_factory=dict)  # requested model -> model to use (agents.<name>.model_map)


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
        if parts[2] == "http" and len(parts) >= 4 and parts[3] in ep.http_mocks:
            req = Request(scope, receive)
            resp = await self._http_mock(ep, parts[3], "/" + "/".join(parts[4:]), req)
            return await resp(scope, receive, send)
        if parts[2] == "mcp" and len(parts) >= 4 and parts[3] in ep.proxies:
            mgr = ep.proxies[parts[3]].manager
            assert mgr is not None
            return await mgr.handle_request(scope, receive, send)
        if parts[2] == "events" and scope.get("method") == "POST":
            resp = await self._events(ep, Request(scope, receive))
            return await resp(scope, receive, send)
        if parts[2] == "v1":
            req = Request(scope, receive)
            tail = "/".join(parts[3:])
            if tail == "chat/completions" and req.method == "POST":
                resp = await self._llm(ep, "openai", await req.json(), req.headers)
            elif tail == "messages" and req.method == "POST":
                resp = await self._llm(ep, "anthropic", await req.json(), req.headers)
            elif tail == "responses" and req.method == "POST":
                resp = await self._llm(ep, "responses", await req.json(), req.headers)
            elif tail == "models":
                resp = JSONResponse({"object": "list", "data": [{"id": self.force_model or "model", "object": "model"}]})
            else:
                resp = JSONResponse({"error": f"unsupported endpoint {tail}"}, 404)
            return await resp(scope, receive, send)
        return await JSONResponse({"error": "not found"}, 404)(scope, receive, send)

    # HTTP mocks ----------------------------------------------------------
    async def _http_mock(self, ep: EpisodeRoutes, name: str, path: str, req: Request) -> Response:
        body = (await req.body()).decode("utf-8", errors="replace")
        route = next((r for r in ep.http_mocks[name]
                      if r.method.upper() in ("*", req.method.upper()) and fnmatch.fnmatchcase(path, r.path)), None)
        ep.rec.add("http_request", mock=name, method=req.method, path=path, query=str(req.url.query),
                   body=clip(body, 2000), status=route.status if route else 404, matched=route is not None)
        if route is None:
            return JSONResponse({"error": f"no mock for {req.method} {path} on {name!r}"}, 404)
        if route.json_body is not None:
            return JSONResponse(route.json_body, route.status, headers=route.headers)
        return Response(route.body or "", route.status, headers=route.headers)

    # LLM proxy (OpenAI Chat Completions + Anthropic Messages) ------------
    def _upstream(self, api: Api, headers: Any) -> tuple[str, dict[str, str]]:
        if api == "anthropic":
            base = (self.llm.anthropic_base_url or self.llm.upstream_base_url.rstrip("/").removesuffix("/v1")).rstrip("/")
            h = {"x-api-key": self.llm.anthropic_api_key or self.llm.api_key,
                 "anthropic-version": headers.get("anthropic-version", "2023-06-01")}
            if headers.get("anthropic-beta"):
                h["anthropic-beta"] = headers["anthropic-beta"]
            return base + "/v1/messages", h
        path = "/responses" if api == "responses" else "/chat/completions"
        return self.llm.upstream_base_url.rstrip("/") + path, {"Authorization": f"Bearer {self.llm.api_key}"}

    async def _llm(self, ep: EpisodeRoutes, api: Api, body: dict[str, Any], headers: Any) -> Response:
        rec = ep.rec
        stream = bool(body.get("stream"))
        ep.requested_model = body.get("model")  # what the agent's own code asked for
        forced = ep.model_map.get(ep.requested_model or "") or ep.model or self.force_model
        if forced:
            body["model"] = forced
        if api == "openai" and stream:
            body["stream_options"] = {**(body.get("stream_options") or {}), "include_usage": True}
        # streamed and non-streamed calls with the same content share a cache entry
        key_body = {k: v for k, v in body.items() if k not in ("stream", "stream_options")}
        key = hashlib.sha256(json.dumps(
            {"api": api, "scenario": rec.scenario_id, "attempt": rec.attempt, "body": key_body},
            sort_keys=True, default=str).encode()).hexdigest()
        cache_file = self.cache_dir / f"{key}.json"
        start = time.monotonic()

        n = ep.llm_n
        ep.llm_n += 1
        seq_file = self.cache_dir / "seq" / f"{rec.scenario_id}--{rec.attempt}.json"
        hit = "hit" if self.llm.cache in ("read_write", "replay") and cache_file.exists() else None
        if hit is None and self.llm.cache == "replay" and seq_file.exists():
            # Exact match missed (tool output with timestamps, ids, durations...): fall back to the
            # response recorded at the same position in this episode, like a cassette.
            seq = json.loads(seq_file.read_text(encoding="utf-8"))
            if n < len(seq) and seq[n]["api"] == api and (self.cache_dir / f"{seq[n]['key']}.json").exists():
                cache_file, hit = self.cache_dir / f"{seq[n]['key']}.json", "hit-seq"
        if hit:
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            if self.llm.cache == "read_write":
                self._remember(ep, seq_file, api, key)
            self._record(rec, api, body, data, start, hit, stream, ep.requested_model)
            if stream:
                return StreamingResponse(as_sse(api, data), media_type="text/event-stream")
            return JSONResponse(data)
        if self.llm.cache == "replay":
            rec.add("llm_call", api=api, model=body.get("model"), error="replay cache miss")
            return JSONResponse({"error": {"message": "agentcrucible replay: no cached response"}}, 409)

        url, up_headers = self._upstream(api, headers)
        cache_state = "miss" if self.llm.cache == "read_write" else "off"
        try:
            upstream = await self.client.send(self.client.build_request("POST", url, json=body, headers=up_headers),
                                              stream=stream)
        except httpx.HTTPError as e:
            rec.add("llm_call", api=api, model=body.get("model"), error=f"upstream unreachable: {e}")
            return JSONResponse({"error": {"message": str(e)}}, 502)
        if upstream.status_code != 200:
            content = await upstream.aread()
            await upstream.aclose()
            rec.add("llm_call", api=api, model=body.get("model"),
                    error=f"upstream {upstream.status_code}: {clip(content.decode(errors='replace'), 300)}")
            return Response(content, upstream.status_code, media_type="application/json")

        if not stream:
            data = upstream.json()
            self._store(cache_file, data)
            if self.llm.cache == "read_write":
                self._remember(ep, seq_file, api, key)
            self._record(rec, api, body, data, start, cache_state, False, ep.requested_model)
            return JSONResponse(data)

        # Real streaming: pass bytes through as they arrive, rebuild the full response alongside.
        acc = accumulator(api)

        async def relay():
            buf = b""
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
                    buf += chunk
                    *lines, buf = buf.split(b"\n")
                    for line in lines:
                        acc.feed(line)
            finally:
                await upstream.aclose()
                if buf:
                    acc.feed(buf)
                data = acc.result()
                self._store(cache_file, data)
                if self.llm.cache == "read_write":
                    self._remember(ep, seq_file, api, key)
                self._record(rec, api, body, data, start, cache_state, True, ep.requested_model)

        return StreamingResponse(relay(), media_type=upstream.headers.get("content-type", "text/event-stream"))

    def _remember(self, ep: EpisodeRoutes, seq_file: Path, api: Api, key: str) -> None:
        ep.llm_seq.append({"api": api, "key": key})
        seq_file.parent.mkdir(parents=True, exist_ok=True)
        seq_file.write_text(json.dumps(ep.llm_seq), encoding="utf-8")

    async def _events(self, ep: EpisodeRoutes, req: Request) -> Response:
        """Tool calls reported by an agent adapter for tools that run inside the agent's own process."""
        try:
            body = await req.json()
        except json.JSONDecodeError:
            return JSONResponse({"error": "body must be JSON"}, 400)
        events = body if isinstance(body, list) else [body]
        n = 0
        for ev in events[:200]:
            if not isinstance(ev, dict) or ev.get("type") not in ("tool_call", "tool_result") or not ev.get("tool"):
                continue
            data = {"tool": str(ev["tool"])[:200], "source": "trace"}
            if ev["type"] == "tool_call":
                data["args"] = ev.get("args") if isinstance(ev.get("args"), dict) else {}
                for flag in ("mocked", "blocked"):
                    if ev.get(flag):
                        data[flag] = True
            else:
                data["content"] = clip(str(ev.get("content", "")))
                data["is_error"] = bool(ev.get("is_error"))
                if isinstance(ev.get("duration_ms"), (int, float)):
                    data["latency_ms"] = round(float(ev["duration_ms"]), 1)
            ep.rec.add(ev["type"], **data)
            n += 1
        return JSONResponse({"recorded": n})

    def _store(self, cache_file: Path, data: dict[str, Any]) -> None:
        if self.llm.cache == "read_write":
            cache_file.parent.mkdir(parents=True, exist_ok=True)
            cache_file.write_text(json.dumps(data), encoding="utf-8")

    def _record(self, rec: Recorder, api: Api, body: dict, data: dict, start: float, cache_state: str,
                streamed: bool, requested_model: str | None = None) -> None:
        s = summarize(api, data)
        rec.add(
            "llm_call",
            api=api,
            model=s.model or body.get("model"),
            tokens_in=s.tokens_in, tokens_out=s.tokens_out,
            cost_usd=round(s.tokens_in / 1000 * self.llm.price_per_1k_input
                           + s.tokens_out / 1000 * self.llm.price_per_1k_output, 6),
            latency_ms=round((time.monotonic() - start) * 1000, 1),
            cache=cache_state,
            stream=streamed,
            finish_reason=s.stop_reason,
            n_messages=len(body.get("messages") or (body["input"] if isinstance(body.get("input"), list) else [1])),
            n_tools=len(body.get("tools") or []),
            content=clip(s.content),
            tool_calls=s.tool_calls,
            tool_requests=s.tool_requests,
            requested_model=requested_model,
        )
