import os
from pathlib import Path

from langchain_openai import ChatOpenAI
from langgraph.checkpoint.memory import MemorySaver
from langgraph.prebuilt import create_react_agent

from .tools import TOOLS

PROMPT_PATH = Path(__file__).parent / "prompts" / "system.md"


def _load_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def build_agent(checkpointer=None):
    model = ChatOpenAI(model=os.getenv("BILLING_MODEL", "gpt-4o"), temperature=0)
    return create_react_agent(
        model,
        tools=TOOLS,
        prompt=_load_prompt(),
        checkpointer=checkpointer,
        name="billing_assistant",
    )


agent = build_agent(MemorySaver())
