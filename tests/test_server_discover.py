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

        pre = c.post("/api/discover/preview", json={"path": str(repo), "use_llm": False}).json()
        assert pre["files"] >= 10 and pre["languages"]["python"] >= 5 and pre["model"] is None
        assert pre["secrets_skipped"] == 0 and isinstance(pre["skipped"], dict)
        assert c.post("/api/discover/preview", json={"path": str(tmp_path)}).status_code == 403

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

        # run cancel_order for real in tests: its drafts then check the database afterwards
        d = c.patch(f"/api/discover/{j['id']}", json={"tools": {"cancel_order": {"mock": False}}}).json()["discovery"]
        asks = next(s for s in d["scenarios"] if s["id"].endswith("cancel-order-asks-first"))
        assert "state.sql" in asks["yaml"] and "cancel_order:" not in asks["yaml"].split("checks:")[0]

        # edit a draft's YAML; an invalid one is refused, a valid one survives re-planning
        sid = next(s["id"] for s in d["scenarios"] if s["id"].endswith("find-customer-uses"))
        bad = c.patch(f"/api/discover/{j['id']}", json={"scenarios": {sid: {"yaml": "id: x\ntask: 1\nchecks: nope"}}})
        assert bad.status_code == 422
        edited = f"id: {sid}\nagent: run-agent\ntask: Look up alex@example.com, please.\nchecks:\n- trajectory.tool_called: find_customer\n"
        d = c.patch(f"/api/discover/{j['id']}", json={"scenarios": {sid: {"yaml": edited}}}).json()["discovery"]
        d = c.patch(f"/api/discover/{j['id']}", json={"agents": {"run-agent": {"purpose": "Helps customers."}}}).json()["discovery"]
        s = next(s for s in d["scenarios"] if s["id"] == sid)
        assert s["yaml"] == edited and s["edited"] is True
        assert c.get(f"/api/discover/{j['id']}/reality").status_code == 404  # no smoke run yet

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


def test_add_a_tool_the_smoke_run_saw(tmp_path, monkeypatch):
    import json

    from agentcrucible.discover import build_plan, discover
    from agentcrucible.discover.synthesize import dump

    repo = tmp_path / "code" / "acme"
    shutil.copytree(DEMO, repo, ignore=shutil.ignore_patterns("agent-tests"))
    d = discover(repo)
    build_plan(d, repo)
    finding = {"kind": "unexpected_tool", "agent": "run-agent", "tool": "lookup_tax_rate",
               "detail": "`lookup_tax_rate` was called 2x but isn't in the map.", "action": "Add it to the agent's tools."}
    job = {
        "id": "abcdef0123", "status": "applied", "source": str(repo), "root": str(repo), "progress": [], "error": None,
        "started": 0, "discovery": dump(d), "result": {"out": str(repo / "agent-tests"), "files": [],
                                                       "validate": {"agents": ["run-agent"], "scenarios": 1, "suites": []},
                                                       "reality": {"findings": [finding]}}}
    with client(tmp_path, monkeypatch) as c:
        jobs = tmp_path / "project" / ".crucible" / "imports"
        jobs.mkdir(parents=True, exist_ok=True)
        (jobs / "abcdef0123.json").write_text(json.dumps(job), encoding="utf-8")
        assert c.post("/api/discover/abcdef0123/tools", json={"agent": "run-agent", "tool": "made_up"}).status_code == 400
        r = c.post("/api/discover/abcdef0123/tools", json={"agent": "run-agent", "tool": "lookup_tax_rate"})
        assert r.status_code == 200, r.text
        j = r.json()
        assert j["status"] == "review" and j["result"]["reality"]["findings"] == []
        d2 = j["discovery"]
        assert "lookup_tax_rate" in d2["agents"][0]["tools"]
        assert any(q["about"] == "tool:lookup_tax_rate" for q in d2["questions"])
        assert any(s["id"].endswith("lookup-tax-rate-uses") for s in d2["scenarios"])  # its tests are drafted
