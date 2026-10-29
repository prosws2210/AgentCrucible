"""Drift check, trace import, Git URL import and the `crucible discover` CLI."""

import json
import shutil
import subprocess
from pathlib import Path

import yaml
from typer.testing import CliRunner

from agentcrucible.cli import app
from agentcrucible.config import Scenario
from agentcrucible.discover import build_plan, check, clone, discover, load
from agentcrucible.discover.traces import read_traces, to_scenarios

DEMO = Path(__file__).resolve().parent.parent / "examples" / "import-demo"
NEW_TOOL = '''

def delete_customer(customer_id: int) -> dict:
    """Permanently delete a customer and their orders."""
    with connect() as db:
        db.execute("DELETE FROM customers WHERE id = ?", (customer_id,))
    return {"ok": True}
'''


def _copy(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests"))
    return repo


def _add_destructive_tool(repo: Path) -> None:
    tools = repo / "acme" / "tools.py"
    tools.write_text(tools.read_text(encoding="utf-8") + NEW_TOOL, encoding="utf-8")
    agent = repo / "acme" / "agent.py"
    src = agent.read_text(encoding="utf-8")
    src = src.replace("from acme.tools import cancel_order,", "from acme.tools import cancel_order, delete_customer,")
    src = src.replace('    "search_help_center": search_help_center,\n}', '    "search_help_center": search_help_center,\n    "delete_customer": delete_customer,\n}')
    schema = ('    {"type": "function", "function": {"name": "delete_customer", "description": "Delete a customer.", '
              '"parameters": {"type": "object", "properties": {"customer_id": {"type": "integer"}}}}},\n]\n\nTOOLS = {')
    src = src.replace("\n]\n\nTOOLS = {", "\n" + schema, 1)  # the model must be able to see it, too
    agent.write_text(src, encoding="utf-8")


def test_drift_flags_a_new_untested_destructive_tool(tmp_path):
    repo = _copy(tmp_path)
    approved = discover(repo)
    build_plan(approved, repo)
    same = check(approved, discover(repo))
    assert not same["fail"] and not same["added_tools"] and "No changes" in same["markdown"]
    assert same["coverage"]["tools_tested"] == same["coverage"]["tools"] == 5

    _add_destructive_tool(repo)
    rep = check(approved, discover(repo))
    added = {t["name"]: t for t in rep["added_tools"]}
    assert "delete_customer" in added and "destructive" in added["delete_customer"]["effects"]
    assert not added["delete_customer"]["tested"] and rep["fail"]
    assert "New tool** `delete_customer`" in rep["markdown"]


def test_trace_import_formats(tmp_path):
    otlp = {"resourceSpans": [{"scopeSpans": [{"spans": [
        {"traceId": "t1", "name": "chat gpt-4o", "startTimeUnixNano": 1, "attributes": [
            {"key": "gen_ai.input.messages", "value": {"stringValue": json.dumps([{"role": "user", "parts": [{"type": "text", "content": "Where is my order A-1001?"}]}])}}]},
        {"traceId": "t1", "name": "execute_tool list_orders", "startTimeUnixNano": 2, "attributes": [
            {"key": "gen_ai.tool.name", "value": {"stringValue": "list_orders"}}]},
        {"traceId": "t2", "name": "llm", "startTimeUnixNano": 3, "attributes": [
            {"key": "llm.input_messages.0.message.role", "value": {"stringValue": "system"}},
            {"key": "llm.input_messages.0.message.content", "value": {"stringValue": "You are helpful."}},
            {"key": "llm.input_messages.1.message.role", "value": {"stringValue": "user"}},
            {"key": "llm.input_messages.1.message.content", "value": {"stringValue": "Refund my mouse please"}}]},
    ]}]}]}
    (tmp_path / "otel.json").write_text(json.dumps(otlp), encoding="utf-8")
    t = read_traces(tmp_path / "otel.json")
    assert [x["input"] for x in t] == ["Where is my order A-1001?", "Refund my mouse please"]
    assert t[0]["tools"] == ["list_orders"]

    runs = [{"id": "r1", "trace_id": "a", "run_type": "chain", "inputs": {"input": "Cancel order A-1002"}, "parent_run_id": None},
            {"id": "r2", "trace_id": "a", "run_type": "tool", "name": "cancel_order", "parent_run_id": "r1"}]
    (tmp_path / "ls.jsonl").write_text("\n".join(json.dumps(r) for r in runs), encoding="utf-8")
    t = read_traces(tmp_path / "ls.jsonl")
    assert t == [{"input": "Cancel order A-1002", "tools": ["cancel_order"], "id": "a"}]

    convs = [{"messages": [{"role": "user", "content": "How long is shipping?"}], "tools": ["search_help_center"]},
             {"messages": [{"role": "user", "content": "How long is shipping?"}]}]  # duplicate task, dropped
    (tmp_path / "c.jsonl").write_text("\n".join(json.dumps(c) for c in convs), encoding="utf-8")
    drafts = to_scenarios(read_traces(tmp_path / "c.jsonl"), agent="run-agent")
    assert len(drafts) == 1
    sc = Scenario.model_validate(yaml.safe_load(drafts[0].yaml))
    assert sc.agent == "run-agent" and sc.task == "How long is shipping?"
    assert sc.checks[0].label == "trajectory.tool_called" and not sc.checks[0].hard


def test_git_url_import(tmp_path):
    src = _copy(tmp_path)
    for args in (["init", "-q"], ["add", "-A"], ["-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init"]):
        subprocess.run(["git", *args], cwd=src, check=True, capture_output=True)
    dest = clone(src.resolve().as_uri(), tmp_path / "imports")
    d = discover(dest, source=src.resolve().as_uri())
    assert [a.id for a in d.agents if a.include] == ["run-agent"] and d.repo.commit


def test_cli_discover_apply_check(tmp_path):
    repo = _copy(tmp_path)
    runner = CliRunner()
    r = runner.invoke(app, ["discover", str(repo), "--no-llm", "--json"])
    assert r.exit_code == 0, r.output
    assert json.loads(r.output)["agents"][0]["id"] == "run-agent"
    r = runner.invoke(app, ["discover", str(repo), "--no-llm", "--apply", "--yes", "--no-smoke"])
    assert r.exit_code == 0, r.output
    out = repo / "agent-tests"
    assert (out / "crucible.yaml").exists() and load(out / "discovery.json").approved
    assert len(list((out / "scenarios" / "run-agent").glob("*.yaml"))) >= 5
    r = runner.invoke(app, ["discover", str(repo), "--no-llm", "--check"])
    assert r.exit_code == 0, r.output
    _add_destructive_tool(repo)
    r = runner.invoke(app, ["discover", str(repo), "--no-llm", "--check"])
    assert r.exit_code == 1 and "delete_customer" in r.output
    r = runner.invoke(app, ["discover", str(repo), "--no-llm", "--update"])
    assert r.exit_code == 0
    draft = load(out / "discovery.draft.json")
    assert any("delete-customer" in s.id for s in draft.scenarios)
