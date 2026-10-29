import json

import anthropic

from . import config
from .tools import HANDLERS, TOOLS

SYSTEM = """You are Helpdesk, a first-line support agent.
Search the knowledge base before answering. Open a ticket when you cannot resolve
the issue. Only page on-call for confirmed customer-facing outages."""

client = anthropic.Anthropic()


def answer_ticket(question: str) -> str:
    messages = [{"role": "user", "content": question}]
    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=2048,
        system=SYSTEM,
        tools=TOOLS,
        messages=messages,
    )

    rounds = 0
    while response.stop_reason == "tool_use" and rounds < config.MAX_TOOL_ROUNDS:
        rounds += 1
        messages.append({"role": "assistant", "content": response.content})
        results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            handler = HANDLERS[block.name]
            try:
                output = handler(**block.input)
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": json.dumps(output, default=str)})
            except Exception as exc:
                results.append({"type": "tool_result", "tool_use_id": block.id, "content": str(exc), "is_error": True})
        messages.append({"role": "user", "content": results})
        response = client.messages.create(
            model=config.ANTHROPIC_MODEL,
            max_tokens=2048,
            system=SYSTEM,
            tools=TOOLS,
            messages=messages,
        )

    return "".join(b.text for b in response.content if b.type == "text")
