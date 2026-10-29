"""Acme's customer-support agent: a hand-written OpenAI tool-calling loop."""

import json
import os
from pathlib import Path

from openai import OpenAI

from acme.tools import cancel_order, find_customer, issue_refund, list_orders, search_help_center

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
SYSTEM_PROMPT = (Path(__file__).parent / "prompts" / "support.md").read_text(encoding="utf-8")

TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "find_customer", "description": "Look up a customer by email address.",
        "parameters": {"type": "object", "properties": {"email": {"type": "string"}}, "required": ["email"]}}},
    {"type": "function", "function": {
        "name": "list_orders", "description": "List a customer's orders.",
        "parameters": {"type": "object", "properties": {"customer_id": {"type": "integer"}}, "required": ["customer_id"]}}},
    {"type": "function", "function": {
        "name": "issue_refund", "description": "Refund a delivered order to the original payment method.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}, "reason": {"type": "string"}},
                       "required": ["order_id", "reason"]}}},
    {"type": "function", "function": {
        "name": "cancel_order", "description": "Cancel an order that has not shipped yet.",
        "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]}}},
    {"type": "function", "function": {
        "name": "search_help_center", "description": "Search help-center articles and return the best match.",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}},
]

TOOLS = {
    "find_customer": find_customer,
    "list_orders": list_orders,
    "issue_refund": issue_refund,
    "cancel_order": cancel_order,
    "search_help_center": search_help_center,
}

client = OpenAI()


def run_agent(messages: list[dict]) -> str:
    """Answer the latest customer message, calling tools as needed."""
    convo = [{"role": "system", "content": SYSTEM_PROMPT}, *messages]
    for _ in range(8):
        response = client.chat.completions.create(model=MODEL, messages=convo, tools=TOOL_SCHEMAS)
        msg = response.choices[0].message
        if not msg.tool_calls:
            return msg.content or ""
        convo.append(msg.model_dump(exclude_none=True))
        for call in msg.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
                result = TOOLS[call.function.name](**args)
            except Exception as e:  # unknown tool or bad arguments: tell the model
                result = {"error": str(e)}
            convo.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)})
    return "Sorry, I couldn't finish that. A human will follow up."
