"""Import API: scan -> review -> apply, folder restrictions and roles."""

import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from agentcrucible.server import create_app

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "examples" / "import-demo"
PROJECT = ROOT / "examples" / "support-agent"


def client(tmp_path, monkeypatch, **env) -> TestClient:
    project = tmp_path / "project"
    shutil.copytree(PROJECT, project, ignore=shutil.ignore_patterns(".crucible"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CRUCIBLE_DISCOVER_ROOTS", str(tmp_path / "code"))
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return TestClient(create_app(project))


def wait(c: TestClient, jid: str, until: tuple[str, ...], timeout: float = 60) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        j = c.get(f"/api/discover/{jid}").json()
        if j["status"] in until:
            return j
        time.sleep(0.2)
    raise AssertionError(f"job stuck in {j['status']}: {j['progress'][-3:]}")


def test_scan_review_apply(tmp_path, monkeypatch):
    repo = tmp_path / "code" / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests"))
    with client(tmp_path, monkeypatch) as c:
        roots = c.get("/api/discover/roots").json()
        assert roots["roots"] == [str((tmp_path / "code").resolve())]
        assert str(repo) in roots["suggestions"]

        r = c.post("/api/discover", json={"path": str(repo), "use_llm": False})
        assert r.status_code == 202, r.text
        j = wait(c, r.json()["id"], ("review", "failed"))
        assert j["status"] == "review", j
        d = j["discovery"]
        assert [a["id"] for a in d["agents"] if a["include"]] == ["run-agent"]
        assert d["plans"][0]["strategy"] == "code" and any("Scanned" in p["message"] for p in j["progress"])

        # review: rename the agent, drop one drafted scenario, mark a tool read-only
        drop = next(s["id"] for s in d["scenarios"] if s["id"].endswith("cancel-order-refuses"))
        r = c.patch(f"/api/discover/{j['id']}", json={
            "agents": {"run-agent": {"name": "Support agent"}},
            "scenarios": {drop: {"include": False}},
            "tools": {"search_help_center": {"effects": ["read-only"]}}})
        assert r.status_code == 200, r.text
        d = r.json()["discovery"]
        assert d["agents"][0]["name"] == "Support agent"
        assert next(s for s in d["scenarios"] if s["id"] == drop)["include"] is False

        r = c.post(f"/api/discover/{j['id']}/apply", json={"smoke": False})
        assert r.status_code == 202, r.text
        j = wait(c, j["id"], ("applied", "apply_failed"))
        assert j["status"] == "applied", j["error"]
        out = repo / "agent-tests"
        assert (out / "crucible.yaml").exists() and j["result"]["validate"]["agents"] == ["run-agent"]
        assert not (out / "scenarios" / "run-agent" / f"{drop}.yaml").exists()

    # a restarted server still knows the job, with the reviewer's edits
    with TestClient(create_app(tmp_path / "project")) as c:
        again = c.get(f"/api/discover/{j['id']}").json()
        assert again["status"] == "applied" and again["discovery"]["agents"][0]["name"] == "Support agent"
        assert c.get("/api/discover/0123456789").status_code == 404


def test_refuses_folders_outside_roots_and_viewers(tmp_path, monkeypatch):
    (tmp_path / "code").mkdir()
    with client(tmp_path, monkeypatch, CRUCIBLE_API_TOKEN="adm", CRUCIBLE_VIEWER_TOKEN="view") as c:
        h = {"Authorization": "Bearer adm"}
        assert c.post("/api/discover", json={"path": str(ROOT)}, headers=h).status_code == 403
        assert c.post("/api/discover", json={"path": str(tmp_path / "nope")}, headers=h).status_code == 400
        assert c.post("/api/discover", json={"git_url": "not a url"}, headers=h).status_code == 400
        assert c.post("/api/discover", json={"path": str(tmp_path / "code")},
                      headers={"Authorization": "Bearer view"}).status_code == 403
        assert c.get("/api/discover/unknown", headers=h).status_code == 404
