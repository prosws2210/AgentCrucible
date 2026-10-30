"""Agents that work on a file (an extraction agent taking `document_path`) get an adapter and a real sample."""

import json
import subprocess
import sys

from agentcrucible.discover import build_plan, discover

BASE = '''
class BaseAgent:
    def __init__(self, name, tools, **kw):
        self.name, self.tools = name, tools

    def invoke(self, task):
        return self._execute_task(task)
'''

AGENT = '''
from app.base import BaseAgent


class ExtractionAgent(BaseAgent):
    def __init__(self, api_key=None, **kw):
        super().__init__(name="extract", tools=[], **kw)

    def _execute_task(self, task):
        path = task.get("document_path")
        name = task.get("original_filename")
        kind = task.get("task_type")
        return {"output": f"{name}: {open(path, encoding='utf-8', errors='replace').read()[:20]}"}
'''


def test_an_agent_that_reads_a_file_gets_the_document_named_in_the_conversation(tmp_path):
    pkg = tmp_path / "app"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("")
    (pkg / "base.py").write_text(BASE)
    (pkg / "extraction.py").write_text(AGENT)
    (tmp_path / "tests" / "fixtures").mkdir(parents=True)
    (tmp_path / "tests" / "fixtures" / "corrupt_invoice.pdf").write_text("%PDF-broken" * 40)
    (tmp_path / "tests" / "fixtures" / "invoice_sample.txt").write_text("INVOICE 42 total 100" * 20)
    d = discover(tmp_path)
    build_plan(d, tmp_path)
    ag = next(a for a in d.agents if a.name.lower().startswith("extraction"))
    plan = next(p for p in d.plans if p.agent == ag.id)
    assert plan.strategy == "code" and "document_from(history)" in plan.adapter_code
    assert '"original_filename": os.path.basename(path)' in plan.adapter_code
    tasks = [s.yaml for s in d.scenarios if s.agent == ag.id]
    assert tasks and all("tests/fixtures/invoice_sample.txt" in t for t in tasks)  # never the broken one

    # the generated adapter runs: it finds the path in the message and hands the file to the agent
    from agentcrucible.discover.apply import write_project
    out, _ = write_project(d, tmp_path)
    proc = subprocess.run([sys.executable, str(out / plan.adapter_file.removeprefix("agent-tests/"))], cwd=tmp_path,
                          input=json.dumps({"type": "user", "content": "Read tests/fixtures/invoice_sample.txt"}) + "\n",
                          capture_output=True, text=True, timeout=60)
    reply = json.loads(proc.stdout.splitlines()[0])["content"]
    assert reply.startswith("invoice_sample.txt: INVOICE 42"), proc.stderr[-500:]


def test_a_constructor_that_takes_keys_gets_the_gateway_s():
    from agentcrucible.discover.plan import _class_py
    from agentcrucible.discover.schema import Agent

    code = _class_py(Agent(id="x", name="X", framework="custom"), "m", "A", "message", ["message"], False, ["."], [],
                     "llm", api_keys=["anthropic_api_key", "openai_api_key"])
    line = next(ln for ln in code.splitlines() if ln.startswith("agent = "))
    assert 'llm=chat_model()' in line and 'anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY")' in line
    assert 'openai_api_key=os.environ.get("OPENAI_API_KEY")' in line and "import os" in code
    compile(code, "adapter.py", "exec")
