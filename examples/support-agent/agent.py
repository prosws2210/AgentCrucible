"""A minimal, framework-free customer-support agent.

It knows nothing about AgentCrucible. It only follows two conventions any real agent already has:
  * the OpenAI SDK reads OPENAI_BASE_URL / OPENAI_API_KEY from the environment
  * MCP server URLs come from configuration (here: CRUCIBLE_MCP_<NAME>_URL env vars)

Protocol (stdio): one JSON object per line.
  in : {"type": "user", "content": "..."}   or   {"type": "end"}
  out: {"type": "assistant", "content": "..."}
"""

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack
from pathlib import Path

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client
from openai import AsyncOpenAI

HERE = Path(__file__).resolve().parent
MAX_STEPS = 8


def log(*a: object) -> None:
    print(*a, file=sys.stderr, flush=True)


async def main() -> None:
    client = AsyncOpenAI(base_url=os.environ.get("OPENAI_BASE_URL"), api_key=os.environ.get("OPENAI_API_KEY", "x"))
    model = os.environ.get("CRUCIBLE_MODEL") or os.environ.get("AGENT_MODEL", "qwen2.5:7b")
    prompt = (HERE / os.environ.get("AGENT_PROMPT", "prompts/v1.md")).read_text(encoding="utf-8")
    servers = {
        k[len("CRUCIBLE_MCP_"):-len("_URL")].lower(): v
        for k, v in os.environ.items()
        if k.startswith("CRUCIBLE_MCP_") and k.endswith("_URL")
    }

    async with AsyncExitStack() as stack:
        sessions: dict[str, ClientSession] = {}
        tools: list[dict] = []
        for name, url in servers.items():
            read, write, _ = await stack.enter_async_context(streamablehttp_client(url))
            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
            for t in (await session.list_tools()).tools:
                sessions[t.name] = session
                tools.append({"type": "function", "function": {
                    "name": t.name, "description": t.description or "", "parameters": t.inputSchema}})
        log(f"agent ready: model={model} tools={[t['function']['name'] for t in tools]}")

        messages: list[dict] = [{"role": "system", "content": prompt}]
        while True:
            line = await asyncio.to_thread(sys.stdin.readline)
            if not line:
                break
            msg = json.loads(line)
            if msg.get("type") == "end":
                break
            messages.append({"role": "user", "content": msg["content"]})
            reply = ""
            for _ in range(MAX_STEPS):
                r = await client.chat.completions.create(model=model, messages=messages, tools=tools, temperature=0.7)
                m = r.choices[0].message
                messages.append(m.model_dump(exclude_none=True))
                if not m.tool_calls:
                    reply = m.content or ""
                    break
                for tc in m.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                        session = sessions[tc.function.name]
                        res = await session.call_tool(tc.function.name, args)
                        text = "\n".join(getattr(c, "text", "") for c in res.content)
                    except Exception as e:  # unknown tool, bad JSON, server error
                        text = f"error: {e}"
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": text})
            else:
                reply = reply or "Sorry, I couldn't complete that."
            print(json.dumps({"type": "assistant", "content": reply}), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
