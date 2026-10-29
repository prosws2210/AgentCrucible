import json
import logging

from openai import OpenAI

from .settings import settings
from .tools import AVAILABLE_FUNCTIONS, TOOL_SCHEMAS

log = logging.getLogger(__name__)
client = OpenAI(api_key=settings.openai_api_key)

SYSTEM_PROMPT = (
    "You are the customer support assistant for Northwind Outfitters. "
    "Use the tools to look up and modify orders. Never cancel an order without "
    "the customer explicitly asking for it."
)


def run_support_agent(user_message: str, history: list[dict] | None = None) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages.extend(history or [])
    messages.append({"role": "user", "content": user_message})

    for _ in range(settings.max_turns):
        response = client.chat.completions.create(
            model=settings.model,
            messages=messages,
            tools=TOOL_SCHEMAS,
            tool_choice="auto",
            temperature=0.2,
        )
        msg = response.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""

        messages.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            fn = AVAILABLE_FUNCTIONS.get(call.function.name)
            try:
                args = json.loads(call.function.arguments or "{}")
                result = fn(**args) if fn else {"error": f"unknown tool {call.function.name}"}
            except Exception as exc:  # surface tool errors back to the model
                log.exception("tool %s failed", call.function.name)
                result = {"error": str(exc)}
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, default=str),
                }
            )
    return "Sorry, I could not finish that request. A human agent will follow up."
