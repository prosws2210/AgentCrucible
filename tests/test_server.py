import shutil
from pathlib import Path

from fastapi.testclient import TestClient

from agentcrucible.server import create_app

EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "support-agent"


def make_client(tmp_path, monkeypatch) -> TestClient:
    project = tmp_path / "project"
    shutil.copytree(EXAMPLE, project, ignore=shutil.ignore_patterns(".crucible"))
    monkeypatch.delenv("DATABASE_URL", raising=False)  # SQLite under the project
    return TestClient(create_app(project))


def test_project_and_empty_history(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        assert c.get("/api/health").json()["db"] == "sqlite"
        p = c.get("/api/project").json()
        assert p["project"] == "support-agent"
        assert set(p["suites"]) == {"core", "security"}
        assert "prompts/v2_fast.md" in p["prompt_presets"]
        assert c.get("/api/runs").json() == []


def test_audit_endpoint_finds_planted_bug(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        r = c.post("/api/audits", json={"server": "shop", "fixture": "fixtures/shop.sql"})
        assert r.status_code == 200, r.text
        a = r.json()
        assert a["grade"] == "D"
        titles = [f["title"] for f in a["report"]["findings"]]
        assert any("SQL injection" in t for t in titles)
        assert c.get("/api/audits").json()[0]["id"] == a["id"]


def test_rejects_arbitrary_servers_and_paths(tmp_path, monkeypatch):
    with make_client(tmp_path, monkeypatch) as c:
        assert c.post("/api/audits", json={"server": "rm -rf /"}).status_code == 400
        assert c.post("/api/audits", json={"server": "shop", "fixture": "../../etc/passwd"}).status_code == 400
        assert c.post("/api/runs", json={"suite": "nope"}).status_code == 400
        assert c.post("/api/runs", json={"agent_env": {"BAD;NAME": "x"}}).status_code == 400
