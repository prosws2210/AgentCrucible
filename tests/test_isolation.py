"""Code under test runs isolated from the server: its environment, credentials and databases."""

from agentcrucible.gateway import child_env


def test_child_env_keeps_the_basics_and_drops_the_servers_secrets(monkeypatch):
    monkeypatch.setenv("PATH", "/usr/bin")
    monkeypatch.setenv("LC_ALL", "C.UTF-8")
    monkeypatch.setenv("DATABASE_URL", "postgresql://crucible:secret@db/crucible")
    monkeypatch.setenv("CRUCIBLE_ANTHROPIC_API_KEY", "sk-ant-real")
    monkeypatch.setenv("CRUCIBLE_API_TOKEN", "token")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-real")
    monkeypatch.setenv("SOMETHING_ELSE", "x")
    monkeypatch.delenv("CRUCIBLE_PASS_ENV", raising=False)
    env = child_env({"PYTHONPATH": "."}, {"OPENAI_API_KEY": "agentcrucible"})
    assert env["PATH"] == "/usr/bin" and env["LC_ALL"] == "C.UTF-8" and env["PYTHONPATH"] == "."
    assert env["OPENAI_API_KEY"] == "agentcrucible"  # later layers win
    for leaked in ("DATABASE_URL", "CRUCIBLE_ANTHROPIC_API_KEY", "CRUCIBLE_API_TOKEN", "SOMETHING_ELSE"):
        assert leaked not in env


def test_the_repos_dotenv_is_neutralised_in_tests_without_reading_values(tmp_path):
    import shutil
    from pathlib import Path

    from agentcrucible.discover import build_plan, discover

    repo = tmp_path / "acme"
    shutil.copytree(Path(__file__).resolve().parent.parent / "examples" / "import-demo", repo,
                    ignore=shutil.ignore_patterns("agent-tests", "__pycache__"))
    (repo / ".env").write_text("DATABASE_URL=postgresql://prod-db/app\nLLM_GATEWAY_ENABLED=true\n"
                               "export OPENAI_API_KEY=sk-live-very-secret\nUPLOAD_DIR=/data/uploads\n", encoding="utf-8")
    (repo / ".env.example").write_text("EXAMPLE_ONLY=1\n", encoding="utf-8")
    d = discover(repo)
    assert d.repo.dotenv == {".env": ["DATABASE_URL", "LLM_GATEWAY_ENABLED", "OPENAI_API_KEY", "UPLOAD_DIR"]}
    assert "sk-live-very-secret" not in d.model_dump_json() and "prod-db" not in d.model_dump_json()
    build_plan(d, repo)
    p = d.plans[0]
    # harmless values of the right shape: a switch stays off, a key is fake, the database is mapped to the test one
    assert p.env["DATABASE_URL"] == "" and p.env["LLM_GATEWAY_ENABLED"] == "" and p.env["OPENAI_API_KEY"] == "agentcrucible-test"
    assert "UPLOAD_DIR" not in p.env  # harmless settings keep the code's own value
    assert any(".env" in w and "test values" in w for w in p.warnings)
    from agentcrucible.discover.plan import test_placeholder
    assert test_placeholder("DO_SPACES_ENDPOINT") == "http://127.0.0.1:9"  # boto3 rejects "" at import
    assert test_placeholder("HTTPS_PROXY") == "" and test_placeholder("SENTRY_DSN") == ""


def test_passing_a_variable_through_is_explicit(monkeypatch):
    monkeypatch.setenv("SOMETHING_ELSE", "x")
    monkeypatch.setenv("ANOTHER", "y")
    assert child_env(inherit=["SOMETHING_ELSE"])["SOMETHING_ELSE"] == "x"
    monkeypatch.setenv("CRUCIBLE_PASS_ENV", "ANOTHER, SOMETHING_ELSE")
    env = child_env()
    assert env["ANOTHER"] == "y" and env["SOMETHING_ELSE"] == "x"


def test_runs_left_running_by_a_stopped_server_are_interrupted_and_cancel_works(tmp_path, monkeypatch):
    import datetime as dt
    import shutil
    from pathlib import Path

    from fastapi.testclient import TestClient

    from agentcrucible.db import Store, make_engine
    from agentcrucible.server import create_app

    project = tmp_path / "project"
    shutil.copytree(Path(__file__).resolve().parent.parent / "examples" / "support-agent", project,
                    ignore=shutil.ignore_patterns(".crucible"))
    monkeypatch.delenv("DATABASE_URL", raising=False)
    store = Store(make_engine(None, project))
    store.add_run(id="run_old", project="support-agent", label="old", suite=None, model="m", status="running",
                  created_at=dt.datetime(2026, 10, 29, 10, 0, tzinfo=dt.timezone.utc), k=3, compare_to=None, params={})
    store.add_run(id="run_q", project="support-agent", label="q", suite=None, model="m", status="done",
                  created_at=dt.datetime(2026, 10, 29, 10, 1, tzinfo=dt.timezone.utc), k=3, compare_to=None, params={})
    with TestClient(create_app(project)) as c:
        assert c.get("/api/runs/run_old").json()["run"]["status"] == "interrupted"
        assert c.post("/api/runs/run_q/cancel").status_code == 409  # finished runs can't be cancelled
        assert c.post("/api/runs/nope/cancel").status_code == 404


def test_episodes_cut_short_by_cancel_are_not_counted_as_failures(tmp_path):
    import asyncio
    import shutil
    from pathlib import Path

    from agentcrucible.config import load_config, load_scenarios
    from agentcrucible.runner import EpisodeResult, Runner, RunOptions

    project = tmp_path / "project"
    shutil.copytree(Path(__file__).resolve().parent.parent / "examples" / "support-agent", project,
                    ignore=shutil.ignore_patterns(".crucible"))
    cfg = load_config(project)
    pairs = [(sc, 1) for sc, _ in load_scenarios(cfg, next(iter(cfg.suites)))][:3]
    runner = Runner(cfg, RunOptions(label="t", parallel=1, out_root=tmp_path / "runs"))
    calls = []
    totals = {"duration_s": 1.0, "llm_calls": 1, "tool_calls": 0, "tokens_in": 1, "tokens_out": 1, "cost_usd": 0.0}

    async def fake_episode(sc, attempt):
        calls.append(sc.id)
        if len(calls) == 1:
            return EpisodeResult(f"e{len(calls)}", sc.id, attempt, True, [], totals)
        runner.cancel()  # Cancel arrives while the second episode runs, and kills its agent
        return EpisodeResult(f"e{len(calls)}", sc.id, attempt, False, [], totals, error="agent exited")

    runner.run_episode = fake_episode  # type: ignore[method-assign]
    run = asyncio.run(runner.run(pairs))
    assert run["cancelled"] and len(calls) == 2  # the third never started
    assert [e["passed"] for e in run["episodes"]] == [True]  # the killed one isn't a failure
