"""An agent that only imports the module reading DATABASE_URL (through a helper) still gets the database."""

from agentcrucible.discover import build_plan, discover

DB = '''
import os
from sqlalchemy import create_engine

engine = create_engine(os.environ["DATABASE_URL"])
'''

HELPER = '''
from app.db import engine


def count_orders():
    with engine.connect() as c:
        return c.exec_driver_sql("select count(*) from orders").scalar()
'''

AGENT = '''
from openai import OpenAI

from app.helpers import count_orders

client = OpenAI()


TOOLS = [{"type": "function", "function": {"name": "count_orders", "description": "How many orders there are.",
                                           "parameters": {"type": "object", "properties": {}}}}]


def answer(message: str) -> str:
    """Answer questions about the shop."""
    messages = [{"role": "user", "content": message}]
    while True:
        reply = client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=TOOLS)
        msg = reply.choices[0].message
        if not msg.tool_calls:
            return msg.content
        messages.append(msg)
        for call in msg.tool_calls:
            messages.append({"role": "tool", "tool_call_id": call.id, "content": str(count_orders())})
'''


def test_the_database_reached_through_imports_is_the_agent_s(tmp_path):
    (tmp_path / "app").mkdir()
    for rel, text in {"app/__init__.py": "", "app/db.py": DB, "app/helpers.py": HELPER, "app/agent.py": AGENT}.items():
        (tmp_path / rel).write_text(text)
    d = discover(tmp_path)
    build_plan(d, tmp_path)
    ag = next(a for a in d.agents if a.include)
    store = next(s for s in d.datastores if s.url_env == "DATABASE_URL")
    assert store.id in ag.datastores
    assert next(p for p in d.plans if p.agent == ag.id).env_map.get("DATABASE_URL") == f"db:{store.id}"
