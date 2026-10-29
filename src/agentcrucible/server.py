"""`crucible serve`: HTTP API for the dashboard.

    GET  /api/health                 liveness + which DB / model endpoint is used
    GET  /api/projects               every test project this server shows (server_projects.py: agents, add by hand)
    GET  /api/project                project, agents, suites, scenarios, MCP servers, prompt presets
    GET  /api/models                 models available on the LLM endpoint
    GET  /api/runs                   run history (with live progress for running ones)
    POST /api/runs                   start a run in the background
    GET  /api/runs/{id}              run detail: per-scenario results + comparison
    GET  /api/runs/{id}/report       self-contained HTML report
    GET  /api/audits                 audit history
    POST /api/audits                 audit one of the project's MCP servers
    GET  /api/audits/{id}            full audit report

Project-scoped endpoints act on the project named by the `X-Crucible-Project` header (or `?project=`), default: the
one the server was started in. Run endpoints find their project from the run itself.
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
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import __version__
from .auth import COOKIE, Tokens
from .auth import middleware as auth_middleware
from .config import load_config, load_scenarios
from .db import Store, make_engine, now
from .projects import Project, Workspace, agent_names, scenario_agent
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
    agent: str | None = None  # only this agent's scenarios
    agent_env: dict[str, str] = Field(default_factory=dict)
    parallel: int = Field(2, ge=1, le=8)


class Login(BaseModel):
    token: str


class AuditRequest(BaseModel):
    server: str
    fixture: str | None = None
    behavioral_model: str | None = None


def create_app(config_path: Path | None = None) -> FastAPI:
    ws = Workspace(config_path)
    store = Store(make_engine(os.environ.get("DATABASE_URL"), ws.home.root))
    lock = asyncio.Lock()
    progress: dict[str, dict[str, int]] = {}
    tasks: set[asyncio.Task] = set()

    def current(request: Request) -> Project:
        pid = request.headers.get("x-crucible-project") or request.query_params.get("project")
        p = ws.get(pid)
        if p is None:
            raise HTTPException(404, f"unknown project {pid!r}")
        return p

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        for p in list(ws.projects.values()):
            await asyncio.to_thread(index_runs, p)  # defined below; runs at startup
        yield

    app = FastAPI(title="AgentCrucible API", version=__version__, lifespan=lifespan)
    tokens = Tokens.from_env()
    app.middleware("http")(auth_middleware(tokens))
    # added last, so it runs first: CORS preflights never hit the auth check
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
                       allow_methods=["*"], allow_headers=["*"], allow_credentials=True)

    # ---------------------------------------------------------------- auth

    @app.get("/api/auth/status")
    async def auth_status(request: Request) -> dict[str, Any]:
        role = tokens.role_for_request(request)
        return {"required": tokens.required, "authenticated": role is not None, "role": role}

    @app.post("/api/auth/login")
    async def login(body: Login, request: Request) -> JSONResponse:
        role = tokens.role_for_token(body.token.strip())
        if role is None:
            await asyncio.sleep(0.5)  # slow down guessing
            raise HTTPException(401, "invalid token")
        resp = JSONResponse({"role": role})
        resp.set_cookie(COOKIE, tokens.session_for(role), httponly=True, samesite="lax", max_age=30 * 86400,
                        secure=request.url.scheme == "https", path="/")
        return resp

    @app.post("/api/auth/logout")
    async def logout() -> JSONResponse:
        resp = JSONResponse({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    def project_of_run(run_id: str) -> Project:
        row = store.get_run(run_id)
        return (ws.by_name(row["project"]) if row else None) or ws.home

    def run_file(run_id: str, p: Project | None = None) -> Path:
        return (p or project_of_run(run_id)).runs_dir / run_id / "run.json"

    def load_run_json(run_id: str, p: Project | None = None) -> dict[str, Any]:
        f = run_file(run_id, p)
        if not f.exists():
            raise HTTPException(404, f"run {run_id} has no results yet")
        return json.loads(f.read_text(encoding="utf-8"))

    def index_runs(p: Project) -> None:
        """Index runs made with the CLI (and import smoke runs) so they show up in the dashboard."""
        try:
            cfg, runs_dir = p.cfg, p.runs_dir
        except Exception:  # noqa: BLE001 - a broken project shouldn't stop the others
            return
        known = store.run_ids()
        for f in sorted(runs_dir.glob("*/run.json")) if runs_dir.exists() else []:
            r = json.loads(f.read_text(encoding="utf-8"))
            if r["run_id"] in known or r.get("shard"):
                continue
            cmp_f = f.parent / "comparison.json"
            cmp = json.loads(cmp_f.read_text(encoding="utf-8")) if cmp_f.exists() else None
            s = r["summary"]
            store.add_run(
                id=r["run_id"], project=cfg.project, label=r.get("label", ""), suite=r.get("suite"),
                model=r["model"], status="done", created_at=dt.datetime.fromisoformat(r["created_at"]),
                finished_at=dt.datetime.fromisoformat(r["created_at"]) + dt.timedelta(seconds=r["duration_s"]),
                k=s["k"], n_episodes=s["n_episodes"], pass_at_1=s["pass_at_1"], pass_pow_k=s["pass_pow_k"],
                compare_to=cmp["base_run"] if cmp else None, verdict=cmp["overall"]["verdict"] if cmp else None,
                gate=("pass" if gate(cmp, r, cfg.ci.fail_on)[0] else "fail"), params={"imported": True, "agent": r.get("agent")},
                summary=_slim_summary(s),
            )

    # ---------------------------------------------------------------- info

    def agent_map(cfg: Any) -> dict[str, str]:
        """scenario id -> the agent it tests"""
        return {sc.id: scenario_agent(cfg, suite, sc) for suite in cfg.suites for sc, _ in load_scenarios(cfg, suite)}

    def latest_results(p: Project) -> dict[str, dict[str, Any]]:
        """Each scenario's result in the newest finished run that included it."""
        latest: dict[str, dict[str, Any]] = {}
        for r in store.list_runs(p.cfg.project):  # newest first
            if r["status"] != "done" or not run_file(r["id"], p).exists():
                continue
            for sid, v in load_run_json(r["id"], p)["summary"]["scenarios"].items():
                latest.setdefault(sid, {"run_id": r["id"], "run_label": r["label"], "passed": v["passed"], "n": v["n"],
                                        "at": r["finished_at"] or r["created_at"]})
        return latest

    @app.get("/api/health")
    async def health(p: Project = Depends(current)) -> dict[str, Any]:
        return {"ok": True, "db": store.engine.dialect.name, "llm_url": p.cfg.llm.upstream_base_url,
                "busy": lock.locked()}

    @app.get("/api/project")
    async def project(p: Project = Depends(current)) -> dict[str, Any]:
        cfg, root = p.cfg, p.root
        amap = agent_map(cfg)
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
        agents = [{"name": n, "scenarios": sum(1 for a in amap.values() if a == n),
                    "suites": [s for s in cfg.suites if (cfg.suites[s].agent or agent_names(cfg)[0]) == n]}
                   for n in agent_names(cfg)]
        return {"id": p.id, "source": p.source, "codebase": p.codebase, "root": str(root), "project": cfg.project,
                "model": cfg.model, "suites": suites, "agents": agents, "discovery": p.discovery_file.is_file(),
                "mcp_servers": list(cfg.mcp_servers), "prompt_presets": presets, "fixtures": fixtures}

    @app.get("/api/models")
    async def models(p: Project = Depends(current)) -> dict[str, Any]:
        cfg = p.cfg
        base = cfg.llm.upstream_base_url.rstrip("/")
        async with httpx.AsyncClient(timeout=10) as http:
            try:
                r = await http.get(base + "/models", headers={"Authorization": f"Bearer {cfg.llm.api_key}"})
                r.raise_for_status()
                return {"ok": True, "models": sorted(m["id"] for m in r.json().get("data", []))}
            except Exception as e:
                return {"ok": False, "models": [], "error": str(e)}

    # ---------------------------------------------------------------- setup

    @app.get("/api/config")
    async def config_summary(p: Project = Depends(current)) -> dict[str, Any]:
        """What this project is connected to (no secrets)."""
        cfg = p.cfg
        a = cfg.agent
        anthropic = cfg.llm.anthropic_base_url or cfg.llm.upstream_base_url.rstrip("/").removesuffix("/v1")
        return {
            "project": cfg.project,
            "agent": {"transport": a.transport, "command": a.command, "url": a.url,
                      "turn_timeout_s": a.turn_timeout_s},
            "agents": [{"name": n, "transport": s.transport, "command": s.command, "url": s.url, "cwd": s.cwd,
                        "turn_timeout_s": s.turn_timeout_s} for n, s in (cfg.agents or {"agent": a}).items()],
            "root": str(p.root),
            "model": cfg.model,
            "llm": {"openai_base_url": cfg.llm.upstream_base_url, "anthropic_base_url": anthropic,
                    "cache": cfg.llm.cache},
            "mcp_servers": [{"name": n, "command": s.command, "url": s.url, "remote": bool(s.url)}
                            for n, s in cfg.mcp_servers.items()],
            "suites": {n: {"path": s.path, "runs": s.runs} for n, s in cfg.suites.items()},
            "simulator_model": cfg.simulator.model,
            "judge_model": cfg.judge.model,
            "gate": {"fail_on": cfg.ci.fail_on, "alpha": cfg.ci.alpha},
        }

    @app.get("/api/doctor")
    async def doctor(p: Project = Depends(current)) -> dict[str, Any]:
        """Live checks that everything a run needs is reachable."""
        from .audit import Target
        cfg, root = p.cfg, p.root
        checks: list[dict[str, Any]] = []
        n_sc = len(load_scenarios(cfg))
        checks.append({"id": "config", "label": "Project configuration", "ok": n_sc > 0,
                       "detail": f"crucible.yaml loaded · {n_sc} scenarios in {len(cfg.suites)} suites"})

        m = await models(p)
        names = set(m["models"])
        has_model = cfg.model in names or f"{cfg.model}:latest" in names
        checks.append({
            "id": "model", "label": "Model server", "ok": bool(m["ok"]) and has_model,
            "detail": (f"{cfg.llm.upstream_base_url} · {cfg.model} available" if has_model
                       else f"{cfg.llm.upstream_base_url} · " + (f"{cfg.model} not found ({len(names)} models)" if m["ok"]
                                                               else f"unreachable: {m.get('error', '')[:120]}")),
        })

        for name, spec in cfg.mcp_servers.items():
            cwd = str((root / spec.cwd).resolve()) if spec.cwd else str(root)
            t = Target(spec.command, spec.url, spec.env, cwd, spec.headers, spec.transport)
            try:
                await asyncio.wait_for(t.connect(), 30)
                tools = (await t.session.list_tools()).tools  # type: ignore[union-attr]
                how = f"reachable at {spec.url}" if spec.url else "started"
                checks.append({"id": f"mcp:{name}", "label": f"MCP server · {name}", "ok": True,
                               "detail": f"{how} · {len(tools)} tools: " + ", ".join(x.name for x in tools[:8])})
            except Exception as e:
                what = (str(e)[:200] if isinstance(e, (PermissionError, ConnectionError)) and spec.url
                        else f"{spec.url} is not reachable: {type(e).__name__}: {str(e)[:160]}" if spec.url
                        else f"`{spec.command}` failed to start: {type(e).__name__}: {str(e)[:160]}")
                checks.append({"id": f"mcp:{name}", "label": f"MCP server · {name}", "ok": False, "detail": what})
            finally:
                await t.close()

        named = cfg.agents or {"agent": cfg.agent}
        for name, a in named.items():
            if a.transport == "http" and not a.command:
                try:
                    async with httpx.AsyncClient(timeout=5) as http:
                        await http.get(a.url or "")
                    ok, detail = True, f"{a.url} is reachable"
                except httpx.HTTPError as e:
                    ok, detail = False, f"{a.url} not reachable: {type(e).__name__}"
            else:
                parts = (a.command or "").split()
                script = next((x for x in parts[1:] if x.endswith((".py", ".js", ".ts", ".mjs"))), None)
                cwd = (root / a.cwd) if a.cwd else root
                ok = script is None or (cwd / script).exists()
                how = "started once per run" if a.transport == "http" else "started once per episode"
                detail = f"`{a.command}` ({a.transport}, {how})" + ("" if ok else f" · {script} not found")
            checks.append({"id": f"agent:{name}" if cfg.agents else "agent",
                           "label": f"Agent · {name}" if cfg.agents else "Agent", "ok": ok, "detail": detail})
        return {"ok": all(c["ok"] for c in checks), "checks": checks}

    @app.get("/api/scenarios")
    async def scenarios(p: Project = Depends(current)) -> list[dict[str, Any]]:
        """Every scenario with its checks and its result in the latest finished run that included it."""
        await asyncio.to_thread(index_runs, p)
        cfg = p.cfg
        latest = await asyncio.to_thread(latest_results, p)
        out = []
        for suite in cfg.suites:
            for sc, runs in load_scenarios(cfg, suite):
                out.append({"id": sc.id, "suite": suite, "agent": scenario_agent(cfg, suite, sc),
                            "description": sc.description, "tags": sc.tags,
                            "runs": runs, "multi_turn": sc.user is not None,
                            "environment": [k for k in ("fixtures", "workspace", "http_mocks", "mocks", "inject", "deny_tools")
                                            if getattr(sc.environment, k)]
                            + (["postgres"] if any(f.kind == "postgres" for f in sc.environment.fixtures.values()) else []),
                            "checks": [{"label": c.label, "hard": c.hard} for c in sc.checks],
                            "task": sc.task, "latest": latest.get(sc.id)})
        return out

    @app.get("/api/runs/{run_id}/episodes/{episode_id}")
    async def episode(run_id: str, episode_id: str) -> dict[str, Any]:
        from .trajectory import load_events
        p = project_of_run(run_id)
        r = load_run_json(run_id, p)
        ep = next((e for e in r["episodes"] if e["episode_id"] == episode_id), None)
        if ep is None:
            raise HTTPException(404, "episode not found")
        f = p.runs_dir / run_id / ep["trajectory"]
        return {**ep, "events": load_events(f) if f.exists() else []}

    # ---------------------------------------------------------------- runs

    @app.get("/api/runs")
    async def list_runs(p: Project = Depends(current)) -> list[dict[str, Any]]:
        await asyncio.to_thread(index_runs, p)
        rows = await asyncio.to_thread(store.list_runs, p.cfg.project)  # one DB serves every project
        for r in rows:
            if r["id"] in progress:
                r["progress"] = progress[r["id"]]
        return rows

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: str) -> dict[str, Any]:
        row = await asyncio.to_thread(store.get_run, run_id)
        if not row:
            raise HTTPException(404, "run not found")
        p = project_of_run(run_id)
        detail: dict[str, Any] = {"run": row, "progress": progress.get(run_id), "project": p.id}
        if run_file(run_id, p).exists():
            r = load_run_json(run_id, p)
            try:
                amap = agent_map(p.cfg)
            except Exception:  # noqa: BLE001
                amap = {}
            detail["scenarios"] = [{"id": sid, **v} for sid, v in r["summary"]["scenarios"].items()]
            detail["summary"] = r["summary"]
            detail["episodes"] = [{k: e[k] for k in ("episode_id", "scenario_id", "attempt", "passed", "error",
                                                     "checks", "totals")} for e in r["episodes"]]
            detail["scenario_meta"] = {sc["id"]: {"description": sc["description"], "tags": sc["tags"],
                                                  "agent": amap.get(sc["id"])} for sc in r["scenarios"]}
            detail["failures"] = [
                {"scenario_id": e["scenario_id"], "attempt": e["attempt"], "error": e.get("error"),
                 "failed_checks": [f"{c['label']}: {c['detail']}" for c in e["checks"] if c["hard"] and not c["passed"]]}
                for e in r["episodes"] if not e["passed"]
            ]
            cmp_f = p.runs_dir / run_id / "comparison.json"
            if cmp_f.exists():
                cmp = json.loads(cmp_f.read_text(encoding="utf-8"))
                detail["comparison"] = {"overall": {k: cmp["overall"][k] for k in ("verdict", "delta", "ci")},
                                        "counts": cmp["counts"], "scenarios": cmp["scenarios"]}
        return detail

    @app.get("/api/runs/{run_id}/report")
    async def report(run_id: str) -> FileResponse:
        p = project_of_run(run_id)
        f = p.runs_dir / run_id / "report.html"
        if not f.exists():
            r = load_run_json(run_id, p)
            cmp_f = f.parent / "comparison.json"
            write_html(f.parent, r, json.loads(cmp_f.read_text(encoding="utf-8")) if cmp_f.exists() else None)
        return FileResponse(f, media_type="text/html")

    @app.post("/api/runs", status_code=202)
    async def start_run(req: RunRequest, p: Project = Depends(current)) -> dict[str, Any]:
        cfg = p.cfg
        try:
            pairs = load_scenarios(cfg, req.suite, req.scenarios)
        except KeyError as e:
            raise HTTPException(400, str(e)) from None
        if req.agent:
            if req.agent not in agent_names(cfg):
                raise HTTPException(400, f"unknown agent {req.agent!r}; known: {', '.join(agent_names(cfg))}")
            amap = agent_map(cfg)
            pairs = [(sc, n) for sc, n in pairs if amap.get(sc.id) == req.agent]
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
        task = asyncio.create_task(_execute(p, run_id, req, pairs, model))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
        return await asyncio.to_thread(store.get_run, run_id)  # type: ignore[return-value]

    async def _execute(p: Project, run_id: str, req: RunRequest, pairs: list, model: str) -> None:
        cfg = p.cfg
        async with lock:  # one run at a time: they share the model server
            await asyncio.to_thread(store.update_run, run_id, status="running")

            def on_episode(res: EpisodeResult) -> None:
                p = progress[run_id]
                p["done"] += 1
                p["failed"] += 0 if res.passed else 1

            try:
                runner = Runner(load_config(p.path), RunOptions(
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
    async def list_audits(p: Project = Depends(current)) -> list[dict[str, Any]]:
        return await asyncio.to_thread(store.list_audits, list(p.cfg.mcp_servers))  # this project's servers only

    @app.get("/api/audits/{audit_id}")
    async def get_audit(audit_id: int) -> dict[str, Any]:
        a = await asyncio.to_thread(store.get_audit, audit_id)
        if not a:
            raise HTTPException(404, "audit not found")
        return a

    @app.post("/api/audits")
    async def run_audit_ep(req: AuditRequest, p: Project = Depends(current)) -> dict[str, Any]:
        from .audit import run_audit
        cfg, root = p.cfg, p.root
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
        rep = await run_audit(spec.command, spec.url, spec.env, cwd, fixture, False, req.behavioral_model,
                              cfg.llm.upstream_base_url, cfg.llm.api_key, spec.headers, spec.transport)
        return await asyncio.to_thread(store.add_audit, req.server, rep.to_dict())

    from .server_discover import register as register_discover
    from .server_projects import register as register_projects
    register_discover(app, ws, lock, index_runs)
    register_projects(app, ws, store, current, lock, latest_results, agent_map, index_runs)

    return app


def _slim_summary(s: dict[str, Any]) -> dict[str, Any]:
    keep = ("n_scenarios", "n_episodes", "k", "pass_at_1", "pass_at_1_ci", "pass_pow_k", "pass_at_k",
            "flaky_scenarios", "errors", "tokens_per_episode", "duration_p50_s", "duration_p95_s")
    return {k: s[k] for k in keep if k in s}
