"""Descriptions from a hosted model (OpenAI or Claude, with the user's key) instead of the local one.

The model calls are replaced by stubs: nothing leaves the machine and no key is needed.
"""

import json
import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcrucible.discover import build_plan, discover
from agentcrucible.discover import synthesize as syn
from agentcrucible.server import create_app

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "import-demo"
PROJECT = ROOT / "examples" / "support-agent"


def answer_for(body: str) -> str:
    batch = json.loads(body[len(syn.ENRICH_PROMPT):])
    return json.dumps({"agents": {a["id"]: f"Agent {a['id']} helps customers." for a in batch["agents"]},
                       "tools": {t["name"]: f"Tool {t['name']}." for t in batch["tools"]}})


def test_claude_descriptions_go_through_the_sdk_in_parallel(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_CACHE_DIR", str(tmp_path / "cache"))
    repo = tmp_path / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    d = discover(repo)
    for t in d.tools:  # the demo's tools have docstrings; without them every tool is sent
        t.description = ""
    calls = []

    def fake_claude(body, model, api_key, timeout):
        calls.append((model, api_key))
        return answer_for(body)

    monkeypatch.setattr(syn, "_ask_claude", fake_claude)
    monkeypatch.setattr(syn, "_ask_openai", lambda *a: (_ for _ in ()).throw(AssertionError("not OpenAI")))
    monkeypatch.setattr(syn, "HOSTED_BATCH", (1, 2, 24000, 40))  # several requests, sent at once
    syn.enrich(d, syn.PROVIDERS["anthropic"], "claude-opus-5-5", "test-key", provider="anthropic")
    assert len(calls) > 1 and set(calls) == {("claude-opus-5-5", "test-key")}
    assert all(a.purpose.startswith("Agent ") for a in d.agents)
    assert all(t.description.startswith("Tool ") for t in d.tools)
    assert d.synthesis["used"] and d.synthesis["requests"] == len(calls) and not d.synthesis["failed"]


def test_hosted_batches_are_bigger_than_local_ones(tmp_path):
    repo = tmp_path / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    d = discover(repo)
    assert len(syn.enrich_batches(d, hosted=True)) <= len(syn.enrich_batches(d))
    assert all(len(json.dumps(b)) <= syn.LOCAL_BATCH[2] + 2000 for b in syn.enrich_batches(d))


def test_the_api_takes_a_provider_and_key_and_never_saves_the_key(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(PROJECT, project, ignore=shutil.ignore_patterns(".crucible"))
    repo = tmp_path / "code" / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("CRUCIBLE_DISCOVER_ROOTS", str(tmp_path / "code"))
    monkeypatch.setenv("CRUCIBLE_CACHE_DIR", str(tmp_path / "cache"))
    seen = []

    def fake_openai(body, base_url, model, api_key, timeout):
        seen.append((base_url, model, api_key))
        return answer_for(body)

    monkeypatch.setattr(syn, "_ask_openai", fake_openai)
    with TestClient(create_app(project)) as c:
        r = c.post("/api/discover", json={"path": str(repo), "llm_provider": "openai", "llm_model": "some-model"})
        assert r.status_code == 400 and "API key" in r.json()["detail"]
        r = c.post("/api/discover", json={"path": str(repo), "llm_provider": "openai", "llm_api_key": "sk-test"})
        assert r.status_code == 400 and "model" in r.json()["detail"]
        jid = c.post("/api/discover", json={"path": str(repo), "llm_provider": "openai", "llm_model": "some-model",
                                            "llm_api_key": "sk-test"}).json()["id"]
        for _ in range(300):
            j = c.get(f"/api/discover/{jid}").json()
            if j["status"] == "review" and not j["describing"]:
                break
            time.sleep(0.2)
        assert seen and seen[0] == (syn.PROVIDERS["openai"], "some-model", "sk-test")
        assert any(a["purpose"].startswith("Agent ") for a in j["discovery"]["agents"])
    saved = (project / ".crucible" / "imports" / f"{jid}.json").read_text(encoding="utf-8")
    assert "sk-test" not in saved


def test_the_key_check_lists_models_and_checks_the_chosen_one(monkeypatch):
    import anthropic

    from agentcrucible.server_discover import LlmCheck, check_hosted_llm

    class FakeModels:
        def __init__(self, key):
            self.key = key

        def list(self, limit=100):
            if self.key != "good":
                raise anthropic.AuthenticationError("bad", response=type("R", (), {"status_code": 401, "headers": {},
                                                                              "request": None})(), body=None)
            return [type("M", (), {"id": i})() for i in ("claude-opus-5-5", "claude-haiku-5-5")]

        def retrieve(self, model):
            if model not in ("claude-opus-5-5", "claude-haiku-5-5"):
                raise anthropic.NotFoundError("no", response=type("R", (), {"status_code": 404, "headers": {},
                                                                            "request": None})(), body=None)

    class FakeClient:
        def __init__(self, api_key=None, **_):
            self.models = FakeModels(api_key)

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = check_hosted_llm(LlmCheck(provider="anthropic", api_key="good", model="claude-haiku-5-5"))
    assert r["ok"] and r["model_ok"] and r["models"][0] == "claude-opus-5-5" and r["key_from"] == "pasted"
    assert check_hosted_llm(LlmCheck(provider="anthropic", api_key="good", model="claude-nope"))["model_ok"] is False
    bad = check_hosted_llm(LlmCheck(provider="anthropic", api_key="bad"))
    assert not bad["ok"] and "rejected" in bad["error"]
    assert "ANTHROPIC_API_KEY" in check_hosted_llm(LlmCheck(provider="anthropic"))["error"]
    monkeypatch.setenv("ANTHROPIC_API_KEY", "good")  # the server's key from .env
    assert check_hosted_llm(LlmCheck(provider="anthropic"))["key_from"] == "server"


def test_older_claude_models_without_effort_still_answer(monkeypatch):
    import anthropic

    sent = []

    class FakeMessages:
        def create(self, **kw):
            sent.append(kw)
            if "output_config" in kw:  # what Sonnet 4.5 answers
                raise anthropic.BadRequestError(
                    "This model does not support the effort parameter.",
                    response=type("R", (), {"status_code": 400, "headers": {}, "request": None})(), body=None)
            block = type("B", (), {"type": "text", "text": '{"agents": {}}'})()
            return type("M", (), {"stop_reason": "end_turn", "content": [block]})()

    class FakeClient:
        def __init__(self, **_):
            self.beta = type("Beta", (), {"messages": FakeMessages()})()

    monkeypatch.setattr(anthropic, "Anthropic", FakeClient)
    syn._NO_EFFORT.discard("claude-sonnet-4-5-20250929")
    assert syn._ask_claude("{}", "claude-sonnet-4-5-20250929", "k", 10) == '{"agents": {}}'
    assert syn._ask_claude("{}", "claude-sonnet-4-5-20250929", "k", 10) == '{"agents": {}}'
    assert ["output_config" in kw for kw in sent] == [True, False, False]  # learned once, then left out


def test_plan_still_builds_after_hosted_descriptions(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_CACHE_DIR", str(tmp_path / "cache"))
    repo = tmp_path / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    d = discover(repo)
    monkeypatch.setattr(syn, "_ask_claude", lambda body, *a: answer_for(body))
    syn.enrich(d, syn.PROVIDERS["anthropic"], "claude-haiku-5-5", "k", provider="anthropic")
    build_plan(d, repo)
    assert d.plans
