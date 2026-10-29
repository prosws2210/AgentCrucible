"""Projects and agents API: imports become projects, agents added by hand (new codebase or an existing project),
per-agent results and runs, and re-imports keeping agents added by hand."""

import json
import shutil
import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from agentcrucible.config import load_config, load_scenarios
from agentcrucible.server import create_app

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "import-demo"
PROJECT = ROOT / "examples" / "support-agent"

BOT = '''def run(message: str) -> str:
    """Answer one message."""
    return "Hello! You said: " + message
'''


def client(tmp_path, monkeypatch) -> TestClient:
    project = tmp_path / "project"
    shutil.copytree(PROJECT, project, ignore=shutil.ignore_patterns(".crucible"))
    (tmp_path / "code").mkdir(exist_ok=True)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CRUCIBLE_DISCOVER_ROOTS", str(tmp_path / "code"))
    return TestClient(create_app(project))


def wait(c: TestClient, jid: str, until: tuple[str, ...], timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = c.get(f"/api/discover/{jid}").json()
        if j["status"] in until:
            return j
        time.sleep(0.2)
    raise AssertionError(f"job stuck in {j['status']}")


def bot_repo(tmp_path) -> Path:
    repo = tmp_path / "code" / "hello-bot"
    (repo / "app").mkdir(parents=True)
    (repo / "app" / "__init__.py").write_text("", encoding="utf-8")
    (repo / "app" / "bot.py").write_text(BOT, encoding="utf-8")
    return repo


def test_home_project_lists_its_agent(tmp_path, monkeypatch):
    with client(tmp_path, monkeypatch) as c:
        projects = c.get("/api/projects").json()
        assert [p["id"] for p in projects] == ["home"] and projects[0]["agents"] == ["agent"]
        agents = c.get("/api/agents").json()
        assert [a["name"] for a in agents] == ["agent"] and agents[0]["scenarios"] > 0
        assert agents[0]["origin"] == "config" and agents[0]["tested"] == 0
        assert all(s["agent"] == "agent" for s in c.get("/api/scenarios").json())
        assert c.get("/api/agents", headers={"X-Crucible-Project": "nope"}).status_code == 404
        assert c.post("/api/runs", json={"agent": "ghost"}).status_code == 400


def test_add_agent_by_hand_starts_a_project_in_a_codebase(tmp_path, monkeypatch):
    repo = bot_repo(tmp_path)
    with client(tmp_path, monkeypatch) as c:
        bad = c.post("/api/agents", json={"name": "Hello bot", "kind": "python", "module": "app.bot", "object": "run",
                                          "task": "Hi", "codebase": str(tmp_path / "project")})
        assert bad.status_code == 403  # outside the allowed folders
        assert c.post("/api/agents", json={"name": "x", "kind": "python", "task": "Hi"}).status_code == 422

        r = c.post("/api/agents", json={
            "name": "Hello bot", "kind": "python", "module": "app.bot", "object": "run", "task": "Say hello to me",
            "reply_mentions": "Hello", "must_not_call": "delete_account", "codebase": str(repo)})
        assert r.status_code == 201, r.text
        pid, aid = r.json()["project"], r.json()["agent"]
        assert aid == "hello-bot" and pid != "home"
        out = repo / "agent-tests"
        cfg = load_config(out)
        assert list(cfg.agents) == ["hello-bot"]
        assert {sc.id for sc, _ in load_scenarios(cfg)} == {"hello-bot-first-test", "hello-bot-smoke"}
        adapter = (out / "adapters" / "hello_bot.py").read_text(encoding="utf-8")
        assert "app.bot" in adapter and "run" in adapter

        assert {p["id"] for p in c.get("/api/projects").json()} == {"home", pid}
        h = {"X-Crucible-Project": pid}
        a = c.get("/api/agents", headers=h).json()
        assert [x["name"] for x in a] == ["hello-bot"] and a[0]["origin"] == "hand" and a[0]["title"] == "Hello bot"
        assert a[0]["connection"]["strategy"] == "code"
        detail = c.get("/api/agents/hello-bot", headers=h).json()
        sc = next(s for s in detail["scenario_list"] if s["id"] == "hello-bot-first-test")
        labels = " | ".join(ch["label"] for ch in sc["checks"])
        assert sc["task"] == "Say hello to me" and "output.contains" in labels and "tool_not_called" in labels, labels
        assert c.get("/api/project", headers=h).json()["agents"][0]["scenarios"] == 2

        # a second agent in the same codebase joins that project
        r = c.post("/api/agents", headers=h, json={"name": "Echo service", "kind": "http", "app_url": "http://localhost:9000",
                                                     "route": "POST /chat", "task": "Echo this"})
        assert r.status_code == 201 and r.json()["project"] == pid, r.text
        cfg = load_config(out)
        assert set(cfg.agents) == {"hello-bot", "echo-service"}
        assert cfg.agents["echo-service"].env["APP_URL"] == "http://localhost:9000"

        # removing an agent deletes the files generated for it; the last agent can't go
        assert c.delete("/api/agents/echo-service", headers=h).json()["result"] == "deleted"
        assert not (out / "scenarios" / "echo-service").exists() and not (out / "adapters" / "echo_service.py").exists()
        assert list(load_config(out).agents) == ["hello-bot"]
        assert c.delete("/api/agents/hello-bot", headers=h).status_code == 400
        c.post("/api/agents", headers=h, json={"name": "Echo service", "kind": "http", "app_url": "http://localhost:9000",
                                               "route": "POST /chat", "task": "Echo this"})

        assert c.delete(f"/api/projects/{pid}").status_code == 200
        assert c.delete("/api/projects/home").status_code == 400
        assert [p["id"] for p in c.get("/api/projects").json()] == ["home"]
        # added back from its folder
        assert c.post("/api/projects", json={"path": str(repo)}).json()["agents"] == ["hello-bot", "echo-service"]


def test_add_agent_to_a_hand_written_project(tmp_path, monkeypatch):
    repo = bot_repo(tmp_path)
    with client(tmp_path, monkeypatch) as c:
        before = {s["id"] for s in c.get("/api/scenarios").json()}
        r = c.post("/api/agents", json={"name": "Hello bot", "kind": "command", "command": "python app/bot_stdio.py",
                                        "task": "Hi there"})
        assert r.status_code == 201 and r.json() == {"project": "home", "agent": "hello-bot"}, r.text
        f = tmp_path / "project" / "crucible.yaml"
        assert (tmp_path / "project" / "crucible.yaml.bak").exists()
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        assert list(data["agents"]) == ["agent", "hello-bot"] and "agent" not in data
        sc = c.get("/api/scenarios").json()
        assert {s["id"] for s in sc} == before | {"hello-bot-first-test"}
        assert {s["agent"] for s in sc if s["id"] in before} == {"agent"}  # the old suites still test the old agent
        assert [a["name"] for a in c.get("/api/agents").json()] == ["agent", "hello-bot"]
        assert c.delete("/api/agents/hello-bot").json()["result"] == "deleted"
        assert [a["name"] for a in c.get("/api/agents").json()] == ["agent"]
        assert c.post("/api/agents", json={"name": "Hello bot", "kind": "command", "command": "python app/bot_stdio.py",
                                           "task": "Hi there"}).status_code == 201

        # a Python function needs an adapter: it is written next to crucible.yaml and started in the codebase
        r = c.post("/api/agents", json={"name": "Bot two", "kind": "python", "module": "app.bot", "object": "run",
                                        "task": "Hi"})
        assert r.status_code == 400 and "no module app.bot" in r.json()["detail"]  # not in this project's folder
        (tmp_path / "project" / "app").mkdir()
        shutil.copy(repo / "app" / "bot.py", tmp_path / "project" / "app" / "bot.py")
        r = c.post("/api/agents", json={"name": "Bot two", "kind": "python", "module": "app.bot", "object": "run",
                                        "task": "Hi"})
        assert r.status_code == 201, r.text
        spec = load_config(f).agents["bot-two"]
        assert spec.cwd == "." and spec.command.endswith("adapters/bot_two.py")
        assert (tmp_path / "project" / "adapters" / "bot_two.py").is_file()


def test_import_becomes_a_project_and_keeps_agents_added_by_hand(tmp_path, monkeypatch):
    repo = tmp_path / "code" / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests"))
    with client(tmp_path, monkeypatch) as c:
        jid = c.post("/api/discover", json={"path": str(repo), "use_llm": False}).json()["id"]
        assert wait(c, jid, ("review", "failed"))["status"] == "review"
        c.post(f"/api/discover/{jid}/apply", json={"smoke": False})
        j = wait(c, jid, ("applied", "apply_failed"))
        assert j["status"] == "applied", j["error"]
        pid = j["result"]["project"]
        h = {"X-Crucible-Project": pid}
        agents = c.get("/api/agents", headers=h).json()
        assert [a["name"] for a in agents] == ["run-agent"] and agents[0]["origin"] == "found"
        assert agents[0]["tools"] and agents[0]["scenarios"] >= 5

        (repo / "extra.py").write_text(BOT, encoding="utf-8")
        r = c.post("/api/agents", headers=h, json={"name": "Extra", "kind": "python", "module": "extra", "object": "run",
                                                     "task": "Hello"})
        assert r.status_code == 201, r.text
        agents = c.get("/api/agents", headers=h).json()
        assert [a["name"] for a in agents] == ["run-agent", "extra"]
        extra = c.get("/api/agents/extra", headers=h).json()
        assert {s["id"] for s in extra["scenario_list"]} == {"extra-first-test", "extra-smoke"}  # not the repo's evals

        # import again: the hand-added agent and its test stay
        jid = c.post("/api/discover", json={"path": str(repo), "use_llm": False}).json()["id"]
        wait(c, jid, ("review", "failed"))
        c.post(f"/api/discover/{jid}/apply", json={"smoke": False})
        j = wait(c, jid, ("applied", "apply_failed"))
        assert j["status"] == "applied" and j["result"]["project"] == pid
        assert "extra" in [a["name"] for a in c.get("/api/agents", headers=h).json()]
        assert (repo / "agent-tests" / "scenarios" / "extra" / "extra-first-test.yaml").exists()
        assert len(c.get("/api/projects").json()) == 2


def test_imports_applied_before_projects_existed_show_up(tmp_path, monkeypatch):
    repo = bot_repo(tmp_path)
    with client(tmp_path, monkeypatch) as c:  # write a project the old way: by hand, then forget it
        r = c.post("/api/agents", json={"name": "Hello bot", "kind": "python", "module": "app.bot", "object": "run",
                                        "task": "Hi", "codebase": str(repo)})
        assert r.status_code == 201
        assert c.delete(f"/api/projects/{r.json()['project']}").status_code == 200
    jobs = tmp_path / "project" / ".crucible" / "imports"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / "0123456789.json").write_text(json.dumps({
        "id": "0123456789", "status": "applied", "root": str(repo), "source": str(repo), "progress": [],
        "result": {"out": str(repo / "agent-tests")}, "discovery": None, "started": 0}), encoding="utf-8")
    with TestClient(create_app(tmp_path / "project")) as c:
        assert [p["source"] for p in c.get("/api/projects").json()] == ["server", "import"]
