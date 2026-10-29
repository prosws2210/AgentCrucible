"""The codebase knowledge graph: what's in it, where it's written, and the API and CLI that serve it."""

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agentcrucible.cli import app as cli
from agentcrucible.discover import build_plan, discover
from agentcrucible.discover.graph import build_graph, viewer_html
from agentcrucible.server import create_app

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "import-demo"
PROJECT = ROOT / "examples" / "support-agent"


def edges_of(g, kind):
    return {(e["source"], e["target"]) for e in g["edges"] if e["kind"] == kind}


def test_graph_maps_files_agents_tools_mcp_and_services(tmp_path):
    repo = tmp_path / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    d = discover(repo)
    build_plan(d, repo)
    g = build_graph(d, repo)
    kinds = {n["kind"] for n in g["nodes"]}
    assert {"agent", "tool", "mcp_server", "file", "datastore"} <= kinds
    agent = next(n for n in g["nodes"] if n["kind"] == "agent")
    assert agent["file"] and agent["line"]  # every finding points at its file and line
    uses = edges_of(g, "uses")
    assert any(a == agent["id"] for a, _ in uses)
    assert (f"file:{agent['file']}", agent["id"]) in edges_of(g, "defines")
    assert edges_of(g, "imports"), "files are linked by their imports"
    assert edges_of(g, "provides"), "the MCP server is linked to its tools"
    assert edges_of(g, "touches"), "tools are linked to the database and APIs they touch"
    html = viewer_html(g)
    assert "/*__GRAPH__*/null" not in html and json.dumps(g["repo"]["name"]) in html
    assert html.count("</script>") == 1  # the embedded data can't close the script early


def test_apply_and_cli_write_the_graph_into_the_repo(tmp_path):
    repo = tmp_path / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    r = CliRunner().invoke(cli, ["discover", str(repo), "--no-llm", "--apply", "--yes", "--no-smoke"])
    assert r.exit_code == 0, r.output
    out = repo / "agent-tests"
    assert (out / "knowledge-graph.json").is_file() and (out / "knowledge-graph.html").is_file()
    (out / "knowledge-graph.json").unlink()
    r = CliRunner().invoke(cli, ["graph", str(repo)])
    assert r.exit_code == 0, r.output
    assert "Knowledge graph: 1 agents" in r.output and (out / "knowledge-graph.json").is_file()


def test_graph_api_for_hand_written_and_imported_projects(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(PROJECT, project, ignore=shutil.ignore_patterns(".crucible"))
    repo = tmp_path / "code" / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CRUCIBLE_DISCOVER_ROOTS", str(tmp_path / "code"))
    with TestClient(create_app(project)) as c:
        g = c.get("/api/graph").json()  # a hand-written project: its code is read to map it
        assert g["counts"].get("mcp_server", 0) >= 1 and (project / "knowledge-graph.html").is_file()
        # the scanned agent is matched to the project's agent, so the dashboard can open its page
        assert {n.get("project_agent") for n in g["nodes"] if n["kind"] == "agent"} == {"agent"}
        assert c.get("/api/graph.html").text.startswith("<!doctype html>")

        import time
        jid = c.post("/api/discover", json={"path": str(repo), "use_llm": False}).json()["id"]
        for _ in range(300):
            if c.get(f"/api/discover/{jid}").json()["status"] == "review":
                break
            time.sleep(0.2)
        jg = c.get(f"/api/discover/{jid}/graph").json()
        assert jg["counts"]["agent"] == 1
        assert "Knowledge graph" in c.get(f"/api/discover/{jid}/graph.html").text
