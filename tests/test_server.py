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


def test_config_doctor_and_scenarios(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_LLM_URL", "http://127.0.0.1:9/v1")  # nothing listens here
    monkeypatch.setenv("CRUCIBLE_LLM_API_KEY", "sk-secret-should-not-leak")
    with make_client(tmp_path, monkeypatch) as c:
        cfg = c.get("/api/config")
        assert cfg.status_code == 200
        assert "sk-secret" not in cfg.text
        assert cfg.json()["agent"]["transport"] == "stdio"
        assert {s["name"] for s in cfg.json()["mcp_servers"]} == {"shop", "docs"}

        d = c.get("/api/doctor").json()
        by_id = {x["id"]: x for x in d["checks"]}
        assert by_id["config"]["ok"]
        assert not by_id["model"]["ok"] and "unreachable" in by_id["model"]["detail"]
        assert by_id["mcp:shop"]["ok"] and "find_customer" in by_id["mcp:shop"]["detail"]
        assert by_id["mcp:docs"]["ok"]
        assert by_id["agent"]["ok"]
        assert d["ok"] is False  # the model server is down

        sc = c.get("/api/scenarios").json()
        assert len(sc) == 10
        refund = next(s for s in sc if s["id"] == "refund-requires-confirmation")
        assert refund["multi_turn"] and "fixtures" in refund["environment"]
        assert {"label": "state.sql", "hard": True} in refund["checks"]
        assert refund["latest"] is None


def test_timestamps_carry_a_timezone(tmp_path):
    """SQLite returns naive datetimes; the API must still say they are UTC (browsers assume local otherwise)."""
    from agentcrucible.db import Store, make_engine, now
    store = Store(make_engine(None, tmp_path))
    store.add_run(id="r1", project="p", label="", suite=None, model="m", status="done", created_at=now(), params={})
    created = store.get_run("r1")["created_at"]
    assert created.endswith("+00:00"), created


def test_auth_tokens_cookie_and_viewer_role(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUCIBLE_API_TOKEN", "admin-tok")
    monkeypatch.setenv("CRUCIBLE_VIEWER_TOKEN", "viewer-tok")
    with make_client(tmp_path, monkeypatch) as c:
        assert c.get("/api/health").status_code == 200  # load balancers need no token
        assert c.get("/api/auth/status").json() == {"required": True, "authenticated": False, "role": None}
        assert c.get("/api/runs").status_code == 401
        assert c.get("/api/runs", headers={"Authorization": "Bearer nope"}).status_code == 401
        assert c.get("/api/runs", headers={"Authorization": "Bearer admin-tok"}).status_code == 200

        assert c.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
        r = c.post("/api/auth/login", json={"token": "viewer-tok"})
        assert r.status_code == 200 and r.json()["role"] == "viewer"
        assert "viewer-tok" not in r.headers["set-cookie"]  # the cookie holds an HMAC, never the token
        assert c.get("/api/auth/status").json()["role"] == "viewer"
        assert c.get("/api/project").status_code == 200
        assert c.post("/api/audits", json={"server": "shop"}).status_code == 403  # read-only

        c.post("/api/auth/logout")
        c.cookies.clear()
        assert c.get("/api/runs").status_code == 401
        assert c.get("/api/runs", cookies={"crucible_session": "admin.forged"}).status_code == 401
        assert c.post("/api/auth/login", json={"token": "admin-tok"}).json()["role"] == "admin"
        assert c.post("/api/runs", json={"suite": "nope"}).status_code == 400  # past auth, rejected on input


def test_auth_off_without_tokens(tmp_path, monkeypatch):
    monkeypatch.delenv("CRUCIBLE_API_TOKEN", raising=False)
    monkeypatch.delenv("CRUCIBLE_VIEWER_TOKEN", raising=False)
    with make_client(tmp_path, monkeypatch) as c:
        assert c.get("/api/auth/status").json() == {"required": False, "authenticated": True, "role": "admin"}
        assert c.get("/api/runs").status_code == 200
