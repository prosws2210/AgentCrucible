"""`crucible serve`: HTTP API for the dashboard.

    GET  /api/health                 liveness + which DB / model endpoint is used
    GET  /api/project                project, suites, scenarios, MCP servers, prompt presets
    GET  /api/models                 models available on the LLM endpoint
    GET  /api/runs                   run history (with live progress for running ones)
    POST /api/runs                   start a run in the background
    GET  /api/runs/{id}              run detail: per-scenario results + comparison
    GET  /api/runs/{id}/report       self-contained HTML report
    GET  /api/audits                 audit history
    POST /api/audits                 audit one of the project's MCP servers
    GET  /api/audits/{id}            full audit report
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import os
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import load_config, load_scenarios
from .db import Store, make_engine, now
from .report import markdown_summary, write_html
from .runner import EpisodeResult, Runner, RunOptions
from .stats import compare_runs, gate


class RunRequest(BaseModel):
    suite: str | None = None
    scenarios: list[str] | None = None
    runs: int = Field(3, ge=1, le=20)
    label: str = ""
    model: str | None = None
    compare: str | None = None  # run id
    agent_env: dict[str, str] = Field(default_factory=dict)
    parallel: int = Field(2, ge=1, le=8)


class AuditRequest(BaseModel):
    server: str
    fixture: str | None = None
    behavioral_model: str | None = None


def create_app(config_path: Path | None = None) -> FastAPI:
    cfg = load_config(config_path)
    root = cfg.root
    runs_dir = root / ".crucible" / "runs"
    store = Store(make_engine(os.environ.get("DATABASE_URL"), root))
    lock = asyncio.Lock()
    progress: dict[str, dict[str, int]] = {}
    tasks: set[asyncio.Task] = set()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await asyncio.to_thread(import_existing)  # defined below; runs at startup
        yield

    app = FastAPI(title="AgentCrucible API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                       allow_methods=["*"], allow_headers=["*"])

    def run_file(run_id: str) -> Path:
        return runs_dir / run_id / "run.json"

    def load_run_json(run_id: str) -> dict[str, Any]:
        f = run_file(run_id)
        if not f.exists():
            raise HTTPException(404, f"run {run_id} has no results yet")
        return json.loads(f.read_text(encoding="utf-8"))

    def import_existing() -> None:
        """Index runs made with the CLI so they show up in the dashboard."""
        known = store.run_ids()
        for f in sorted(runs_dir.glob("*/run.json")) if runs_dir.exists() else []:
            r = json.loads(f.read_text(encoding="utf-8"))
            if r["run_id"] in known or r.get("shard"):
                continue
            cmp_f = f.parent / "comparison.json"
            cmp = json.loads(cmp_f.read_text(encoding="utf-8")) if cmp_f.exists() else None
            s = r["summary"]
            store.add_run(
                id=r["run_id"], project=r["project"], label=r.get("label", ""), suite=r.get("suite"),
                model=r["model"], status="done", created_at=dt.datetime.fromisoformat(r["created_at"]),
                finished_at=dt.datetime.fromisoformat(r["created_at"]) + dt.timedelta(seconds=r["duration_s"]),
                k=s["k"], n_episodes=s["n_episodes"], pass_at_1=s["pass_at_1"], pass_pow_k=s["pass_pow_k"],
                compare_to=cmp["base_run"] if cmp else None, verdict=cmp["overall"]["verdict"] if cmp else None,
                gate=("pass" if gate(cmp, r, cfg.ci.fail_on)[0] else "fail"), params={"imported": True},
                summary=_slim_summary(s),
            )

    # ---------------------------------------------------------------- info

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "db": store.engine.dialect.name, "llm_url": cfg.llm.upstream_base_url,
                "busy": lock.locked()}

    @app.get("/api/project")
    async def project() -> dict[str, Any]:
        suites = {}
        for name in cfg.suites:
            pairs = load_scenarios(cfg, name)
            suites[name] = {"runs": cfg.suites[name].runs,
                            "scenarios": [{"id": sc.id, "description": sc.description, "tags": sc.tags}
                                          for sc, _ in pairs]}
        prompts_dir = root / "prompts"
        presets = sorted(p.relative_to(root).as_posix() for p in prompts_dir.glob("*.md")) if prompts_dir.exists() else []
        fixtures = sorted(p.relative_to(root).as_posix() for p in (root / "fixtures").glob("*.sql")) \
            if (root / "fixtures").exists() else []
        return {"project": cfg.project, "model": cfg.model, "suites": suites,
                "mcp_servers": list(cfg.mcp_servers), "prompt_presets": presets, "fixtures": fixtures}

    @app.get("/api/models")
    async def models() -> dict[str, Any]:
        base = cfg.llm.upstream_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=10) as http:
            try:
                r = await http.get(base + "/models", headers={"Authorization": f"Bearer {cfg.llm.api_key}"})
                r.raise_for_status()
                return {"ok": True, "models": sorted(m["id"] for m in r.json().get("data", []))}
            except Exception as e:
                return {"ok": False, "models": [], "error": str(e)}

    # ---------------------------------------------------------------- runs

    @app.get("/api/runs")
    async def list_runs() -> list[dict[str, Any]]:
        rows = await asyncio.to_thread(store.list_runs, cfg.project)  # one DB can serve several projects
        for r in rows:
            if r["id"] in progress:
                r["progress"] = progress[r["id"]]
        return rows

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(store.get_run, run_id)
        if not row:
            raise HTTPException(404, "run not found")
        detail: dict[str, Any] = {"run": row, "progress": progress.get(run_id)}
        if run_file(run_id).exists():
            r = load_run_json(run_id)
            detail["scenarios"] = [{"id": sid, **v} for sid, v in r["summary"]["scenarios"].items()]
            detail["failures"] = [
                {"scenario_id": e["scenario_id"], "attempt": e["attempt"], "error": e.get("error"),
                 "failed_checks": [f"{c['label']}: {c['detail']}" for c in e["checks"] if c["hard"] and not c["passed"]]}
                for e in r["episodes"] if not e["passed"]
            ]
            cmp_f = runs_dir / run_id / "comparison.json"
            if cmp_f.exists():
                cmp = json.loads(cmp_f.read_text(encoding="utf-8"))
                detail["comparison"] = {"overall": {k: cmp["overall"][k] for k in ("verdict", "delta", "ci")},
                                        "counts": cmp["counts"], "scenarios": cmp["scenarios"]}
        return detail

    @app.get("/api/runs/{run_id}/report")
    async def report(run_id: str) -> FileResponse:
        f = runs_dir / run_id / "report.html"
        if not f.exists():
            r = load_run_json(run_id)
            cmp_f = f.parent / "comparison.json"
            write_html(f.parent, r, json.loads(cmp_f.read_text(encoding="utf-8")) if cmp_f.exists() else None)
        return FileResponse(f, media_type="text/html")

    @app.post("/api/runs", status_code=202)
    async def start_run(req: RunRequest) -> dict[str, Any]:
        try:
            pairs = load_scenarios(cfg, req.suite, req.scenarios)
        except KeyError as e:
            raise HTTPException(400, str(e)) from None
        if not pairs:
            raise HTTPException(400, "no scenarios matched")
        if req.compare and not run_file(req.compare).exists():
            raise HTTPException(400, f"baseline run {req.compare} has no results")
        for k in req.agent_env:
            if not k.replace("_", "").isalnum():
                raise HTTPException(400, f"invalid env var name {k!r}")
        pairs = [(sc, req.runs) for sc, _ in pairs]
        run_id = f"run_{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}_{uuid.uuid4().hex[:4]}"
        model = req.model or cfg.model
        await asyncio.to_thread(
            store.add_run, id=run_id, project=cfg.project, label=req.label, suite=req.suite, model=model,
            status="queued", created_at=now(), k=req.runs, compare_to=req.compare,
            params=req.model_dump(),
        )
        progress[run_id] = {"done": 0, "total": sum(r for _, r in pairs), "failed": 0}
        task = asyncio.create_task(_execute(run_id, req, pairs, model))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return await asyncio.to_thread(store.get_run, run_id)  # type: ignore[return-value]

    async def _execute(run_id: str, req: RunRequest, pairs: list, model: str) -> None:
        async with lock:  # one run at a time: they share the model server
            await asyncio.to_thread(store.update_run, run_id, status="running")

            def on_episode(res: EpisodeResult) -> None:
                p = progress[run_id]
                p["done"] += 1
                p["failed"] += 0 if res.passed else 1

            try:
                runner = Runner(load_config(config_path), RunOptions(
                    label=req.label, parallel=req.parallel, model=model, agent_env=req.agent_env, run_id=run_id,
                ), on_episode)
                # Own thread + event loop: episodes spawn processes and grade synchronously in places,
                # and must never stall API requests.
                result = await asyncio.to_thread(asyncio.run, runner.run(pairs, req.suite))
                cmp = None
                if req.compare:
                    cmp = compare_runs(load_run_json(req.compare), result, cfg.ci.alpha)
                    (runner.run_dir / "comparison.json").write_text(json.dumps(cmp, indent=2), encoding="utf-8")
                write_html(runner.run_dir, result, cmp)
                (runner.run_dir / "summary.md").write_text(markdown_summary(result, cmp), encoding="utf-8")
                ok, _ = gate(cmp, result, cfg.ci.fail_on)
                s = result["summary"]
                await asyncio.to_thread(
                    store.update_run, run_id, status="done", finished_at=now(), n_episodes=s["n_episodes"],
                    pass_at_1=s["pass_at_1"], pass_pow_k=s["pass_pow_k"], k=s["k"],
                    verdict=cmp["overall"]["verdict"] if cmp else None, gate="pass" if ok else "fail",
                    summary=_slim_summary(s),
                )
            except Exception as e:
                await asyncio.to_thread(store.update_run, run_id, status="failed", finished_at=now(),
                                        error=f"{type(e).__name__}: {e}")
            finally:
                progress.pop(run_id, None)

    # ---------------------------------------------------------------- audits

    @app.get("/api/audits")
    async def list_audits() -> list[dict[str, Any]]:
        return await asyncio.to_thread(store.list_audits, list(cfg.mcp_servers))  # this project's servers only

    @app.get("/api/audits/{audit_id}")
    async def get_audit(audit_id: int) -> dict[str, Any]:
        a = await asyncio.to_thread(store.get_audit, audit_id)
        if not a:
            raise HTTPException(404, "audit not found")
        return a

    @app.post("/api/audits")
    async def run_audit_ep(req: AuditRequest) -> dict[str, Any]:
        from .audit import run_audit
        # Only the project's own servers can be audited: the API never runs arbitrary commands.
        spec = cfg.mcp_servers.get(req.server)
        if spec is None:
            raise HTTPException(400, f"unknown MCP server {req.server!r}; known: {list(cfg.mcp_servers)}")
        fixture = None
        if req.fixture:
            fixture = (root / req.fixture).resolve()
            if root.resolve() not in fixture.parents or not fixture.is_file():
                raise HTTPException(400, "fixture must be a file inside the project")
        cwd = str((root / spec.cwd).resolve()) if spec.cwd else str(root)
        rep = await run_audit(spec.command, None, spec.env, cwd, fixture, False, req.behavioral_model,
                              cfg.llm.upstream_base_url, cfg.llm.api_key)
        return await asyncio.to_thread(store.add_audit, req.server, rep.to_dict())

    return app


def _slim_summary(s: dict[str, Any]) -> dict[str, Any]:
    keep = ("n_scenarios", "n_episodes", "k", "pass_at_1", "pass_at_1_ci", "pass_pow_k", "pass_at_k",
            "flaky_scenarios", "errors", "tokens_per_episode", "duration_p50_s", "duration_p95_s")
    return {k: s[k] for k in keep if k in s}
