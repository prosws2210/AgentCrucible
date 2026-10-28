"""A coding agent running as an HTTP service, built on the official Anthropic SDK (streaming).

It knows nothing about AgentCrucible. Like many agent services it is stateless: each request carries
the conversation plus a `context` telling it which model endpoint and MCP servers to use.
Under test, AgentCrucible fills `context` with its gateways; in production your platform would.

    POST /turn   {"messages": [{"role": "user", "content": "..."}, ...],
                  "context": {"anthropic_base_url", "api_key", "model", "mcp": {name: url}, "env": {...}}}
    ->           {"content": "<final reply>"}
"""

import argparse
import os
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any

import uvicorn
from anthropic import AsyncAnthropic
from fastapi import FastAPI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from pydantic import BaseModel, Field

HERE = Path(__file__).resolve().parent
MAX_STEPS = 12

app = FastAPI(title="coding agent")


class Turn(BaseModel):
    episode_id: str | None = None
    messages: list[dict[str, Any]]
    context: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/turn")
async def turn(t: Turn) -> dict[str, str]:
    ctx = t.context
    env = {**os.environ, **(ctx.get("env") or {})}
    system = (HERE / env.get("AGENT_PROMPT", "prompts/system.md")).read_text(encoding="utf-8")
    client = AsyncAnthropic(
        base_url=ctx.get("anthropic_base_url") or env.get("ANTHROPIC_BASE_URL"),
        api_key=ctx.get("api_key") or env.get("ANTHROPIC_API_KEY", "missing"),
    )
    model = ctx.get("model") or env.get("AGENT_MODEL", "claude-sonnet-4-5")

    async with AsyncExitStack() as stack:
        sessions: dict[str, ClientSession] = {}
        tools: list[dict[str, Any]] = []
        for url in (ctx.get("mcp") or {}).values():
            read, write, _ = await stack.enter_async_context(streamablehttp_client(url))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            for tool in (await session.list_tools()).tools:
                sessions[tool.name] = session
                tools.append({"name": tool.name, "description": tool.description or "",
                              "input_schema": tool.inputSchema})

        messages: list[dict[str, Any]] = [{"role": m["role"], "content": m["content"]} for m in t.messages]
        for _ in range(MAX_STEPS):
            async with client.messages.stream(model=model, max_tokens=2048, system=system,
                                              messages=messages, tools=tools) as stream:
                msg = await stream.get_final_message()
            messages.append({"role": "assistant", "content": [b.model_dump(exclude_none=True) for b in msg.content]})
            uses = [b for b in msg.content if b.type == "tool_use"]
            if not uses:
                return {"content": "".join(b.text for b in msg.content if b.type == "text").strip()}
            results = []
            for use in uses:
                try:
                    res = await sessions[use.name].call_tool(use.name, use.input or {})
                    text = "\n".join(getattr(c, "text", "") for c in res.content)
                    is_error = bool(res.isError)
                except Exception as e:  # unknown tool or server error
                    text, is_error = f"error: {e}", True
                results.append({"type": "tool_result", "tool_use_id": use.id, "content": text, "is_error": is_error})
            messages.append({"role": "user", "content": results})
        return {"content": "I stopped after too many steps without finishing."}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8701)
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")
