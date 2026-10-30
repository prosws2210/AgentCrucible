"""Paths pasted from the host reach the folder mounted into the container, and the scan is quick on slow mounts."""

import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from agentcrucible.discover.scan import scan
from agentcrucible.server import create_app
from agentcrucible.server_discover import looks_like_host_path, to_server_path

ROOT = Path(__file__).resolve().parent.parent


def test_host_paths_map_to_the_mount(monkeypatch):
    monkeypatch.setenv("CRUCIBLE_PATH_MAP", "D:/Work=/import;D:/Work/big=/big")
    assert to_server_path(r"D:\Work\billing-service") == "/import/billing-service"
    assert to_server_path(r"d:\work") == "/import"  # Windows paths ignore case
    assert to_server_path(r'"D:\Work\big\svc"') == "/big/svc"  # the longest mount wins; quotes are dropped
    assert to_server_path(r"D:\WorkX\repo") == r"D:\WorkX\repo"  # only whole folder names match
    assert to_server_path("/workspace/examples") == "/workspace/examples"
    monkeypatch.setenv("CRUCIBLE_PATH_MAP", "=/import")  # CRUCIBLE_IMPORT_DIR not set
    assert to_server_path(r"D:\code") == r"D:\code"


@pytest.mark.skipif(os.name == "nt", reason="a Windows server reads Windows paths itself")
def test_a_windows_path_on_a_container_says_how_to_mount_it(tmp_path, monkeypatch):
    project = tmp_path / "project"
    shutil.copytree(ROOT / "examples" / "support-agent", project, ignore=shutil.ignore_patterns(".crucible"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("CRUCIBLE_DISCOVER_ROOTS", str(tmp_path))
    assert looks_like_host_path(r"D:\code\repo") and not looks_like_host_path("/import/repo")
    with TestClient(create_app(project)) as c:
        r = c.post("/api/discover/preview", json={"path": r"D:\code\repo", "use_llm": False})
        assert r.status_code == 400 and "CRUCIBLE_IMPORT_DIR" in r.json()["detail"]


def test_connection_check_imports_each_agent_and_names_the_missing_package(tmp_path):
    from agentcrucible.discover import build_plan, discover
    from agentcrucible.discover.apply import connection_check, write_project

    repo = tmp_path / "acme"
    shutil.copytree(ROOT / "examples" / "import-demo", repo, ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    d = discover(repo)
    build_plan(d, repo)
    out, _ = write_project(d, repo)
    ag = next(a for a in d.agents if a.include)
    ok = {c["id"]: c for c in connection_check(out, None, d, repo)}
    assert ok[f"agent:{ag.id}"]["ok"], ok[f"agent:{ag.id}"]["detail"]  # the demo's own code imports fine
    src = repo / (ag.entrypoint.module.replace(".", "/") + ".py")
    src.write_text("import surely_not_installed_pkg\n" + src.read_text(encoding="utf-8"), encoding="utf-8")
    bad = {c["id"]: c for c in connection_check(out, None, d, repo)}[f"agent:{ag.id}"]
    assert not bad["ok"] and bad["missing"] == "surely_not_installed_pkg" and "crucible run" in bad["detail"]


def test_scan_keeps_walk_order_and_skips(tmp_path):
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "agent.py").write_text("x = 1\n")
    (tmp_path / "a.py").write_text("y = 2\n")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "dep.js").write_text("")
    (tmp_path / ".env").write_text("KEY=1")
    (tmp_path / "big.json").write_text("0" * (1024 * 1024 + 10))
    inv = scan(tmp_path)
    assert [f.rel for f in inv.files] == ["a.py", "b/agent.py"]
    assert inv.skipped_secret == [".env"] and inv.skip_reasons["files over 1 MB"] == 1
    inv.prefetch()
    assert inv.files[0].text == "y = 2\n"


def test_a_reimported_project_starts_without_the_old_runs(tmp_path):
    from agentcrucible.server_discover import archive_old_runs

    out = tmp_path / "agent-tests"
    (out / ".crucible" / "runs" / "run_1").mkdir(parents=True)
    (out / ".crucible" / "runs" / "run_1" / "run.json").write_text("{}")
    (out / "crucible.yaml").write_text("project: acme\n")
    assert archive_old_runs(out) == "acme"
    assert not (out / ".crucible" / "runs").exists()
    archived = list((out / ".crucible" / "runs-archive").glob("*/run_1/run.json"))
    assert len(archived) == 1  # moved, not deleted
    assert archive_old_runs(out) is None  # nothing left to archive
