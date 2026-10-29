"""RAG document snapshots: drafted from the repo's own documents, searched per query, used by in-process and MCP mocks."""

import json
import os

import yaml

from agentcrucible.config import load_config, load_scenarios
from agentcrucible.discover import build_plan, discover
from agentcrucible.discover.apply import write_project
from agentcrucible.discover.plan import SNAPSHOT_FILE
from agentcrucible.snapshot import answer, build, query_of, search

AGENT = '''import chromadb
from openai import OpenAI

client = OpenAI()
store = chromadb.PersistentClient(path="index").get_collection("docs")
TOOLS = [{"type": "function", "function": {"name": "search_docs", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}]


def search_docs(query: str) -> str:
    """Search the product documentation."""
    return store.query(query_texts=[query])


def run(message: str) -> str:
    r = client.chat.completions.create(model="gpt-4.1", messages=[{"role": "user", "content": message}], tools=TOOLS)
    return r.choices[0].message.content
'''


def repo(tmp_path):
    root = tmp_path / "rag"
    (root / "app").mkdir(parents=True)
    (root / "app" / "agent.py").write_text(AGENT, encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs" / "returns.md").write_text("# Returns\n\nItems can be returned within 30 days for a full refund.\n\n"
                                              "Opened software cannot be returned.", encoding="utf-8")
    (root / "docs" / "shipping.md").write_text("# Shipping\n\nStandard shipping takes 3 to 5 business days.",
                                               encoding="utf-8")
    (root / "docs" / "api_key.md").write_text("token = 'sk-abcdefghijklmnopqrstuvwxyz123456'", encoding="utf-8")
    return root


def test_search_ranks_passages_and_reads_tool_arguments(tmp_path):
    f = tmp_path / "snap.json"
    f.write_text(json.dumps(build([("returns.md", "Items can be returned within 30 days."),
                                   ("shipping.md", "Standard shipping takes 3 to 5 business days.")])), encoding="utf-8")
    assert search(f, "how many days do I have to return something?")[0]["source"] == "returns.md"
    assert search(f, "zebra telescope") == []
    assert query_of({"query": "a", "k": 3}) == "a" and query_of({"filter": "x", "text_to_find": "longer text"}) == "longer text"
    assert answer({"snapshot": str(f)}, {"q": "shipping days"}).startswith("[shipping.md]")
    assert answer({"snapshot": str(f)}, {"q": "zebra"}) == "No results."


def test_import_drafts_rag_tests_against_a_snapshot_of_the_docs(tmp_path):
    root = repo(tmp_path)
    d = discover(root)
    build_plan(d, root)
    assert [v.kind for v in d.vector_stores] == ["chroma"]
    assert d.documents == ["docs/api_key.md", "docs/returns.md", "docs/shipping.md"]
    grounded = yaml.safe_load(next(s.yaml for s in d.scenarios if s.id.endswith("grounded-answer")))
    assert grounded["environment"]["mocks"]["search_docs"] == {"snapshot": SNAPSHOT_FILE, "k": 3}
    out, _ = write_project(d, root)
    snap = json.loads((out / SNAPSHOT_FILE).read_text(encoding="utf-8"))
    assert {p["source"] for p in snap["passages"]} >= {"docs/returns.md", "agentcrucible/kb-118.md"}
    assert "sk-abcdef" not in json.dumps(snap)  # secrets in documents are redacted like everywhere else
    cfg = load_config(out)
    sc = next(sc for sc, _ in load_scenarios(cfg) if sc.id.endswith("grounded-answer"))
    mock = sc.environment.mocks["search_docs"]
    assert os.path.isabs(mock["snapshot"])  # resolved against crucible.yaml, so any process can open it
    assert "HARBOR-7" in answer(mock, {"query": "free shipping code for big orders"})

    # the reviewer can still choose a fixed passage
    for v in d.vector_stores:
        v.test_with = "mock"
    build_plan(d, root)
    fixed = yaml.safe_load(next(s.yaml for s in d.scenarios if s.id.endswith("grounded-answer")))
    assert isinstance(fixed["environment"]["mocks"]["search_docs"], str)


def test_mcp_retriever_answers_from_the_snapshot(tmp_path):
    import asyncio

    from agentcrucible.config import Environment
    from agentcrucible.gateway import McpProxy
    from agentcrucible.trajectory import Recorder

    f = tmp_path / "snap.json"
    f.write_text(json.dumps(build([("faq.md", "The warranty lasts two years from delivery.")])), encoding="utf-8")
    rec = Recorder("e", "s", 1)
    proxy = McpProxy.__new__(McpProxy)
    proxy.name, proxy.rec = "kb", rec
    proxy.environment = Environment(mocks={"search": {"snapshot": str(f), "k": 1}})
    res = asyncio.run(proxy._handle_call("search", {"query": "how long is the warranty"}))
    assert "two years" in res.content[0].text and rec.events[-1]["type"] == "tool_result"


def test_in_process_retriever_answers_from_the_snapshot(tmp_path, monkeypatch):
    from agentcrucible.adapters import _wrap_callable

    f = tmp_path / "snap.json"
    f.write_text(json.dumps(build([("faq.md", "The warranty lasts two years from delivery.")])), encoding="utf-8")
    monkeypatch.setenv("CRUCIBLE_TOOL_MOCKS", json.dumps({"search_docs": {"snapshot": str(f)}}))
    monkeypatch.delenv("CRUCIBLE_EVENTS_URL", raising=False)

    def search_docs(query: str) -> str:
        raise AssertionError("the real retriever must not run in tests")

    assert "two years" in _wrap_callable(search_docs, "search_docs")("warranty length?")
