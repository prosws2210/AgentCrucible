"""An orchestrator with no agent class, wired up where a web route calls it, is found and driven the route's way."""

import json
import subprocess
import sys

from agentcrucible.discover import build_plan, discover

ROUTE = '''
from app.chat.pipeline import run_turn
from app.models import SharedComposer, SharedModelClassifier


class _Router:
    def post(self, path):
        return lambda f: f


router = _Router()


@router.post("/chat")
async def chat(body: dict):
    query = body["text"]
    tenant_id = body["tenant"]
    return await run_turn(tenant_id=tenant_id, text=query,
                          classifier=SharedModelClassifier(tenant_id=tenant_id), composer=SharedComposer())
'''

PIPELINE = '''
async def run_turn(*, tenant_id, text, classifier, composer):
    """Answer one chat turn: route it, run the lane, compose the reply."""
    return {"content": f"{tenant_id}|{classifier.label(text)}|{composer.name}"}
'''

MODELS = '''
class SharedModelClassifier:
    def __init__(self, tenant_id):
        self.tenant_id = tenant_id

    def label(self, text):
        return "invoice" if "invoice" in text.lower() else "other"


class SharedComposer:
    name = "composer"
'''

LANES = '''
from langchain_core.tools import tool


@tool
def lookup_invoice(number: str) -> str:
    """Find an invoice by its number."""
    return number
'''


def test_the_route_s_call_becomes_the_agent_with_its_package_tools(tmp_path):
    (tmp_path / "app" / "chat").mkdir(parents=True)
    for rel, text in {"app/__init__.py": "", "app/chat/__init__.py": "", "app/routes.py": ROUTE, "app/models.py": MODELS,
                      "app/chat/pipeline.py": PIPELINE, "app/chat/lanes.py": LANES}.items():
        (tmp_path / rel).write_text(text)
    d = discover(tmp_path)
    build_plan(d, tmp_path)
    ag = next(a for a in d.agents if a.name == "Chat Run Turn")  # named after its package and function
    assert ag.include and "lookup_invoice" in ag.tools  # the tools of its own package are its tools
    assert ag.purpose.startswith("Answer one chat turn")  # from its docstring
    plan = next(p for p in d.plans if p.agent == ag.id)
    assert plan.strategy == "code" and "TEST_VALUES" in plan.adapter_code

    from agentcrucible.discover.apply import write_project
    out, _ = write_project(d, tmp_path)
    proc = subprocess.run([sys.executable, str(out / plan.adapter_file.removeprefix("agent-tests/"))], cwd=tmp_path,
                          input=json.dumps({"type": "user", "content": "Where is invoice 42?"}) + "\n",
                          capture_output=True, text=True, timeout=60)
    reply = json.loads(proc.stdout.splitlines()[0])["content"]
    assert reply == "00000000-0000-4000-8000-000000000001|invoice|composer", proc.stderr[-800:]
