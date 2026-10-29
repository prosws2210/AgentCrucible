"""Codebase import, the parts beyond the basics: monorepos, auth, memory, prompts loaded at run time, Django/Drizzle
tables, queues, README examples, state checks, suggested code changes, stale scenarios and the synthesis cache."""

import json
import threading
import time

import uvicorn
import yaml
from fastapi import FastAPI, Request
from typer.testing import CliRunner

from agentcrucible.cli import app as cli
from agentcrucible.discover import build_plan, check, discover
from agentcrucible.discover.plan import apply_fixes
from agentcrucible.gateway import free_port
from agentcrucible.server_discover import answer_questions

FILES = {
    "services/billing/pyproject.toml": '[project]\nname = "billing"\n',
    "services/support/pyproject.toml": '[project]\nname = "support"\n',
    "services/billing/billing/agent.py": '''from fastapi import FastAPI, Depends
from openai import OpenAI
from langgraph.checkpoint.memory import MemorySaver
from celery import Celery

client = OpenAI(base_url="http://10.0.0.5:8000/v1")
queue = Celery("billing", broker="redis://localhost")
app = FastAPI()


def current_user():
    return "x"


TOOLS = [{"type": "function", "function": {"name": "close_invoice", "parameters": {"type": "object", "properties": {"invoice_id": {"type": "string"}}}}}]


def close_invoice(invoice_id: str):
    """Close an invoice."""
    return {"ok": True}


def run(message: str) -> str:
    r = client.chat.completions.create(model="gpt-4.1", messages=[{"role": "user", "content": message}], tools=TOOLS)
    return r.choices[0].message.content


@app.post("/chat")
def chat(body: dict, user=Depends(current_user)):
    return {"reply": run(body["message"])}
''',
    "services/support/support/models.py": '''from django.db import models


class Ticket(models.Model):
    subject = models.CharField(max_length=200)
    status = models.CharField(max_length=20)
''',
    "services/support/support/agent.py": '''from anthropic import Anthropic
from langfuse import Langfuse

client = Anthropic()
langfuse = Langfuse()
TOOLS = [{"name": "resolve_ticket", "input_schema": {"type": "object", "properties": {"ticket_id": {"type": "integer"}}}}]


def resolve_ticket(ticket_id: int):
    """Mark a ticket resolved."""
    db.execute("UPDATE support_ticket SET status = 'resolved' WHERE id = ?", (ticket_id,))


def run(message):
    prompt = langfuse.get_prompt("support")
    return client.messages.create(model="claude-sonnet-4", max_tokens=500, system=prompt.prompt,
                                  messages=[{"role": "user", "content": message}], tools=TOOLS)
''',
    "services/support/db/schema.ts": 'import { pgTable, serial, text } from "drizzle-orm/pg-core";\n'
                                     'export const notes = pgTable("notes", { id: serial("id"), body: text("body") });\n',
    "README.md": "# Mono\n\n```bash\ncurl -X POST localhost:8000/chat -d '{\"message\": \"Please close invoice INV-7 for me\"}'\n```\n",
}


def monorepo(tmp_path):
    root = tmp_path / "mono"
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    return root


def test_monorepo_context(tmp_path):
    root = monorepo(tmp_path)
    d = discover(root)
    build_plan(d, root)
    by_service = {a.service: a for a in d.agents}
    billing, support = by_service["services/billing"], by_service["services/support"]
    assert billing.name.startswith("Billing ·") and support.name.startswith("Support ·")  # both were called "Run"
    assert billing.memory == "MemorySaver" and support.memory is None
    assert billing.entrypoint.kind == "code" and any("POST /chat" in n for n in billing.notes)
    assert not any("POST /chat" in n for n in support.notes)  # the route lives in billing, which defines its own `run`
    about = {q.about: q for q in d.questions}
    assert f"auth:{billing.id}" in about and f"auth:{support.id}" not in about
    prompt_q = about[f"prompt:{support.id}"]
    assert "loads its prompt" in prompt_q.text
    answer_questions(d, {prompt_q.id: prompt_q.options[1]})  # "no, a fixed copy": a note, and the agent stays in
    assert support.include and any("fixed copy of the prompt" in n for n in support.notes)
    tables = {t for s in d.datastores for t in s.tables}
    assert {"support_ticket", "notes"} <= tables  # Django <app>_<model>, Drizzle pgTable
    assert [(x.id, x.kind) for x in d.external_apis] == [("celery", "queue")]
    assert any("celery queue" in w for p in d.plans for w in p.warnings)
    assert [t["input"] for t in d.test_cases] == ["Please close invoice INV-7 for me"]
    assert d.generator["agentcrucible"] and d.generator["detectors"]


def test_state_checks_use_typed_examples(tmp_path):
    root = monorepo(tmp_path)
    d = discover(root)
    build_plan(d, root)
    t = d.tool("resolve_ticket")
    assert t.sql_writes == ["UPDATE support_ticket SET status = 'resolved' WHERE id = ?"]
    sc = yaml.safe_load(next(s.yaml for s in d.scenarios if s.id.endswith("resolve-ticket-uses")))
    assert "ticket_id: 1" in sc["task"]  # an integer id points at the first seeded row
    assert {"state.sql": {"db": "app", "query": "SELECT status FROM support_ticket WHERE id = 1", "expect": "resolved"}} in sc["checks"]


def test_suggested_base_url_change_is_applied_only_when_accepted(tmp_path):
    root = monorepo(tmp_path)
    agent = root / "services/billing/billing/agent.py"
    d = discover(root)
    build_plan(d, root)
    fix = next(fx for p in d.plans for fx in p.fixes)
    assert fix.add_import == "import os"  # the file doesn't import it yet
    assert 'os.environ.get("OPENAI_BASE_URL", "http://10.0.0.5:8000/v1")' in fix.new
    assert apply_fixes(d, root) == [] and "environ" not in agent.read_text(encoding="utf-8")
    fix.accept = True
    build_plan(d, root)  # re-planning keeps the reviewer's choice
    assert next(fx for p in d.plans for fx in p.fixes).accept
    assert apply_fixes(d, root) == [fix.id]
    src = agent.read_text(encoding="utf-8")
    assert src.startswith("import os\n") and 'base_url=os.environ.get("OPENAI_BASE_URL"' in src
    compile(src, str(agent), "exec")


def test_removed_tool_makes_scenarios_stale(tmp_path):
    root = monorepo(tmp_path)
    approved = discover(root)
    build_plan(approved, root)
    agent = root / "services/support/support/agent.py"
    agent.write_text(agent.read_text(encoding="utf-8").replace("resolve_ticket", "reopen_ticket"), encoding="utf-8")
    rep = check(approved, discover(root))
    assert "resolve_ticket" in rep["removed_tools"]
    assert any(s.endswith("resolve-ticket-uses") for s in rep["stale_scenarios"]) and "Stale scenarios" in rep["markdown"]


def test_check_report_file_for_pr_comments(tmp_path):
    root = monorepo(tmp_path)
    r = CliRunner().invoke(cli, ["discover", str(root), "--no-llm", "--apply", "--yes", "--no-smoke"])
    assert r.exit_code == 0, r.output
    assert not any(f.startswith("agent-tests/") for fact in discover(root).facts.values() for f in [fact.evidence[0].file])
    report = tmp_path / "drift.md"
    r = CliRunner().invoke(cli, ["discover", str(root), "--no-llm", "--check", "--report", str(report)])
    assert r.exit_code == 0, r.output
    assert report.read_text(encoding="utf-8").startswith("<!-- crucible-discover -->\n## AgentCrucible")


def test_use_draft_applies_the_reviewed_file(tmp_path):
    root = monorepo(tmp_path)
    runner = CliRunner()
    assert runner.invoke(cli, ["discover", str(root), "--no-llm"]).exit_code == 0
    draft = root / "agent-tests" / "discovery.draft.json"
    data = json.loads(draft.read_text(encoding="utf-8"))
    for a in data["agents"]:
        a["include"] = a["service"] == "services/support"  # the reviewer keeps one agent
    draft.write_text(json.dumps(data), encoding="utf-8")
    r = runner.invoke(cli, ["discover", str(root), "--apply", "--use-draft", "--yes", "--no-smoke"])
    assert r.exit_code == 0, r.output
    cfg = yaml.safe_load((root / "agent-tests" / "crucible.yaml").read_text(encoding="utf-8").split("\n", 3)[-1])
    assert len(cfg["agents"]) == 1


def test_synthesis_is_cached_by_content(tmp_path, monkeypatch):
    calls = []
    model = FastAPI()

    @model.get("/v1/models")
    async def models():
        return {"data": [{"id": "tiny"}]}

    @model.post("/v1/chat/completions")
    async def chat(req: Request):
        body = await req.json()
        calls.append(body)
        return {"choices": [{"message": {"role": "assistant", "content": json.dumps({"agents": {}, "tools": {}, "questions": []})}}]}

    port = free_port()
    server = uvicorn.Server(uvicorn.Config(model, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    monkeypatch.setenv("CRUCIBLE_CACHE_DIR", str(tmp_path / "cache"))
    root = monorepo(tmp_path)
    try:
        first = discover(root, llm_base_url=f"http://127.0.0.1:{port}/v1", llm_model="tiny")
        second = discover(root, llm_base_url=f"http://127.0.0.1:{port}/v1", llm_model="tiny")
    finally:
        server.should_exit = True
        th.join(5)
    assert len(calls) == first.synthesis["requests"] == 1 and second.synthesis["cached"] == 1
    sent = first.synthesis["sent"]
    assert sent and all({"fact", "file", "line"} <= set(s) for s in sent)  # what the model saw, for the review screen
    assert "sk-" not in json.dumps(calls)


def test_langgraph_tools_from_other_modules_and_graph_names(tmp_path):
    """Patterns from real LangGraph templates: a TOOLS list imported from tools.py, `bind_tools` inside a node with a
    module-attribute tool, and the graph's name from compile(name=...) rather than the builder variable."""
    root = tmp_path / "lg"
    pkg = root / "src" / "notes_agent"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "tools.py").write_text('''async def search(query: str) -> str:
    """Search the web."""
    return requests.get("https://api.example.com/search", params={"q": query}).text


async def save_note(text: str) -> str:
    """Save a note for later."""
    await store.aput(("notes",), "id", {"text": text})
    return "saved"


TOOLS = [search]
''', encoding="utf-8")
    (pkg / "graph.py").write_text('''from langchain_openai import ChatOpenAI
from langgraph.graph import StateGraph
from langgraph.prebuilt import ToolNode

from notes_agent import tools
from notes_agent.tools import TOOLS


async def call_model(state):
    return {"messages": [await ChatOpenAI(model="gpt-4o-mini").bind_tools([tools.save_note]).ainvoke(state["messages"])]}


builder = StateGraph(dict)
builder.add_node(call_model)
builder.add_node("tools", ToolNode(TOOLS))
graph = builder.compile(name="Notes Agent")
''', encoding="utf-8")
    d = discover(root)
    ag = next(a for a in d.agents if a.include)
    assert ag.name == "Notes Agent" and sorted(ag.tools) == ["save_note", "search"]
    effects = {t.name: t.effects for t in d.tools}
    assert "writes data" in effects["save_note"] and "external call" in effects["search"]


def test_openai_agents_generic_agents_and_handoff_calls(tmp_path):
    """From the OpenAI Agents SDK customer-service example: Agent[Context](...) and handoffs=[handoff(agent=...)]."""
    root = tmp_path / "cs"
    root.mkdir()
    (root / "main.py").write_text('''from agents import Agent, function_tool, handoff


@function_tool
def faq_lookup(question: str) -> str:
    """Look up an FAQ answer."""
    return "Bags up to 23kg are free."


faq_agent = Agent[dict](name="FAQ Agent", instructions="Answer FAQs.", tools=[faq_lookup])
triage_agent = Agent[dict](name="Triage Agent", instructions="Route the request.",
                           handoffs=[handoff(agent=faq_agent, tool_name_override="transfer_to_faq")])
''', encoding="utf-8")
    d = discover(root)
    included = [a for a in d.agents if a.include]
    assert [(a.name, a.framework) for a in included] == [("Triage Agent", "openai-agents")]
    assert included[0].subagents == ["faq-agent"] and included[0].tools == ["faq_lookup"]


def test_apply_refuses_without_agents(tmp_path):
    import pytest

    from agentcrucible.discover import apply

    root = monorepo(tmp_path)
    d = discover(root)
    build_plan(d, root)
    for a in d.agents:
        a.include = False
    with pytest.raises(ValueError, match="nothing to test"):
        apply(d, root, smoke=False)
