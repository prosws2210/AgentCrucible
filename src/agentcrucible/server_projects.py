"""API for projects and their agents (dashboard: project switcher, Agents, Add agents).

    GET    /api/projects                every project, with its agents, scenarios and latest results
    POST   /api/projects                {path}: add an existing test project (a folder with crucible.yaml)
    DELETE /api/projects/{id}           remove it from the dashboard (its files stay)
    GET    /api/agents                  the current project's agents, with what they are and how they're doing
    GET    /api/agents/{name}           one agent: connection, tools, scenarios with results, recent runs
    POST   /api/agents                  add an agent by hand to the current project, or start a project in a codebase
    DELETE /api/agents/{name}           remove an agent (found ones are switched off, hand-added ones deleted)
    GET    /api/graph[.html]            the project's knowledge graph (JSON, or the viewer); also saved in the repository

Adding an agent by hand writes files only inside the project folder (and `agent-tests/` of the chosen codebase), and
only folders under CRUCIBLE_DISCOVER_ROOTS can be chosen, like for imports.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ValidationError

from .add_agent import NewAgent, add_to_config, add_to_discovery, remove_agent
from .config import find_config
from .db import Store
from .discover.plan import OUT_DIR
from .discover.schema import Discovery
from .projects import HOME, Project, Workspace, agent_names
from .server_discover import roots_from_env

SECRETISH = re.compile(r"key|token|secret|password|passwd|pwd|auth", re.I)


class AddProject(BaseModel):
    path: str


class AddAgent(NewAgent):
    codebase: str | None = None  # start a new project in this folder instead of adding to the current one


def _discovery(p: Project) -> Discovery | None:
    f = p.discovery_file
    if not f.is_file():
        return None
    try:
        return Discovery.model_validate_json(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def register(app: FastAPI, ws: Workspace, store: Store, current: Callable[[Request], Project], lock: asyncio.Lock,
             latest_results: Callable[[Project], dict[str, dict[str, Any]]],
             agent_map: Callable[[Any], dict[str, str]], index_runs: Callable[[Project], None]) -> None:

    def allowed(path: Path) -> bool:
        p = path.resolve()
        return any(p == r or r in p.parents for r in roots_from_env(ws.home.cfg))

    def summary(p: Project) -> dict[str, Any]:
        out = ws.summary(p)
        if out["error"]:
            return {**out, "last_run": None}
        rows = store.list_runs(p.cfg.project, limit=1)
        last = rows[0] if rows else None
        out["last_run"] = {k: last[k] for k in ("id", "label", "status", "pass_at_1", "created_at", "gate")} if last else None
        return out

    @app.get("/api/projects")
    async def list_projects() -> list[dict[str, Any]]:
        for p in list(ws.projects.values()):
            await asyncio.to_thread(index_runs, p)
        return [await asyncio.to_thread(summary, p) for p in ws.projects.values()]

    @app.post("/api/projects")
    async def add_project(body: AddProject) -> dict[str, Any]:
        path = Path(body.path).expanduser()
        if not path.exists() or not allowed(path):
            raise HTTPException(403 if path.exists() else 400,
                                "that folder is outside CRUCIBLE_DISCOVER_ROOTS" if path.exists() else f"{path} doesn't exist")
        cand = path / OUT_DIR if path.is_dir() and (path / OUT_DIR / "crucible.yaml").is_file() else path
        try:
            f = cand if cand.is_file() else find_config(cand)
        except FileNotFoundError:
            raise HTTPException(400, f"no crucible.yaml in {path} (import the codebase instead)") from None
        if not allowed(f):
            raise HTTPException(403, "that crucible.yaml is outside CRUCIBLE_DISCOVER_ROOTS")
        try:
            p = ws.register(f, "added", codebase=str(f.parent.parent) if f.parent.name == OUT_DIR else None)
        except Exception as e:  # noqa: BLE001
            raise HTTPException(400, f"crucible.yaml doesn't load: {type(e).__name__}: {str(e)[:300]}") from None
        await asyncio.to_thread(index_runs, p)
        return await asyncio.to_thread(summary, p)

    @app.delete("/api/projects/{pid}")
    async def remove_project(pid: str) -> dict[str, Any]:
        if pid == HOME:
            raise HTTPException(400, "the server's own project can't be removed")
        if not ws.remove(pid):
            raise HTTPException(404, "unknown project")
        return {"ok": True}

    # ---------------------------------------------------------------- agents

    def agent_rows(p: Project) -> list[dict[str, Any]]:
        cfg = p.cfg
        amap = agent_map(cfg)
        latest = latest_results(p)
        d = _discovery(p)
        tools = {t.name: t for t in d.tools} if d else {}
        plans = {pl.agent: pl for pl in d.plans} if d else {}
        out = []
        for name in agent_names(cfg):
            spec = cfg.agents.get(name) or cfg.agent
            ag = d.agent(name) if d else None
            sids = [s for s, a in amap.items() if a == name]
            res = [latest[s] for s in sids if s in latest]
            plan = plans.get(name)
            out.append({
                "name": name,
                "title": ag.name if ag else name,
                "purpose": ag.purpose if ag else "",
                "framework": ag.framework if ag else None,
                "language": ag.language if ag else None,
                "origin": "hand" if ag and ag.added_by_hand else "found" if ag else "config",
                "service": ag.service if ag else None,
                "transport": spec.transport if spec else None,
                "command": spec.command if spec else None,
                "url": spec.url if spec else None,
                "cwd": spec.cwd if spec else None,
                "env": {k: ("•••" if SECRETISH.search(k) else v) for k, v in (spec.env if spec else {}).items()},
                "connection": {"strategy": plan.strategy, "why": plan.why, "adapter_file": plan.adapter_file,
                               "env_needed": plan.env_needed, "warnings": plan.warnings} if plan else None,
                "model": (ag.model.value or ag.model.env) if ag else None,
                "test_model": (spec.model if spec and spec.model else None) or cfg.model,
                "model_map": dict(spec.model_map) if spec else {},
                "memory": ag.memory if ag else None,
                "subagents": ag.subagents if ag else [],
                "mcp_servers": ag.mcp_servers if ag else [],
                "tools": [{"name": t, "effects": tools[t].effects if t in tools else [],
                           "description": tools[t].description if t in tools else "",
                           "mock": tools[t].mock if t in tools else None} for t in (ag.tools if ag else [])],
                "suites": [s for s in cfg.suites if (cfg.suites[s].agent or agent_names(cfg)[0]) == name],
                "scenarios": len(sids),
                "tested": len(res),
                "passed": sum(r["passed"] for r in res),
                "episodes": sum(r["n"] for r in res),
                "failing": sum(1 for r in res if r["passed"] < r["n"]),
                "last_tested": max((r["at"] for r in res), default=None),
            })
        return out

    @app.get("/api/agents")
    async def list_agents(p: Project = Depends(current)) -> list[dict[str, Any]]:
        await asyncio.to_thread(index_runs, p)
        return await asyncio.to_thread(agent_rows, p)

    @app.get("/api/agents/{name}")
    async def get_agent(name: str, p: Project = Depends(current)) -> dict[str, Any]:
        await asyncio.to_thread(index_runs, p)
        rows = await asyncio.to_thread(agent_rows, p)
        row = next((r for r in rows if r["name"] == name), None)
        if row is None:
            raise HTTPException(404, f"no agent {name!r} in this project")
        cfg = p.cfg
        amap = agent_map(cfg)
        latest = await asyncio.to_thread(latest_results, p)
        from .config import load_scenarios
        scen = [{"id": sc.id, "suite": suite, "description": sc.description, "task": sc.task, "tags": sc.tags,
                 "checks": [{"label": c.label, "hard": c.hard} for c in sc.checks], "multi_turn": sc.user is not None,
                 "latest": latest.get(sc.id)}
                for suite in cfg.suites for sc, _ in load_scenarios(cfg, suite) if amap.get(sc.id) == name]
        mine = {s["id"] for s in scen}
        runs = []
        for r in await asyncio.to_thread(store.list_runs, cfg.project, 50):
            f = p.runs_dir / r["id"] / "run.json"
            agent = (r.get("params") or {}).get("agent")
            if agent not in (None, name) or not f.exists() and r["status"] == "done":
                continue
            row_r = {k: r[k] for k in ("id", "label", "status", "model", "created_at", "pass_at_1", "gate")}
            row_r["agent"] = agent
            if f.exists():
                sc_res = json.loads(f.read_text(encoding="utf-8"))["summary"]["scenarios"]
                own = [v for k, v in sc_res.items() if k in mine]
                if not own:
                    continue
                row_r["passed"], row_r["n"] = sum(v["passed"] for v in own), sum(v["n"] for v in own)
            runs.append(row_r)
            if len(runs) >= 10:
                break
        return {**row, "scenario_list": scen, "runs": runs}

    @app.post("/api/agents", status_code=201)
    async def add_agent(body: dict[str, Any], p: Project = Depends(current)) -> dict[str, Any]:
        try:
            req = AddAgent.model_validate(body)
        except ValidationError as e:
            first = e.errors()[0]
            raise HTTPException(422, str(first.get("msg", "invalid")).removeprefix("Value error, ")) from None
        home = ws.home.cfg
        if req.codebase:  # a new project in a codebase (or the one already there)
            codebase = Path(req.codebase).expanduser()
            if not codebase.is_dir():
                raise HTTPException(400, f"{codebase} is not a folder this server can see")
            if not allowed(codebase):
                raise HTTPException(403, "that folder is outside CRUCIBLE_DISCOVER_ROOTS")
            out = codebase / OUT_DIR
            target = ws.for_path(out / "crucible.yaml") if (out / "crucible.yaml").is_file() else None
            if target is None and (out / "crucible.yaml").is_file() and not (out / "discovery.json").is_file():
                raise HTTPException(409, f"{out} has a hand-written crucible.yaml: add it as a project first")
        else:
            target = p
            out = p.root
            codebase = Path(p.codebase) if p.codebase else None
            d = _discovery(p)
            if codebase is None:
                codebase = Path(d.repo.root) if d else p.root
        async with lock:  # don't rewrite a project while a run reads it
            try:
                if (out / "discovery.json").is_file() or req.codebase:
                    aid = await asyncio.to_thread(add_to_discovery, out, codebase, req, home.model,
                                                  home.llm.upstream_base_url)
                else:
                    aid = await asyncio.to_thread(add_to_config, target.path, codebase, req)  # type: ignore[union-attr]
            except (ValueError, OSError) as e:
                raise HTTPException(400, f"{type(e).__name__}: {str(e)[:400]}") from None
        if target is not None:
            target.invalidate()
        proj = target if target is not None else ws.register(out / "crucible.yaml", "manual", codebase=str(codebase))
        return {"project": proj.id, "agent": aid}

    @app.delete("/api/agents/{name}")
    async def delete_agent(name: str, p: Project = Depends(current)) -> dict[str, Any]:
        home = ws.home.cfg
        d = _discovery(p)
        codebase = Path(p.codebase) if p.codebase else Path(d.repo.root) if d else p.root
        async with lock:
            try:
                what = await asyncio.to_thread(remove_agent, p.root, p.path, codebase, name, home.model,
                                               home.llm.upstream_base_url)
            except (ValueError, OSError) as e:
                raise HTTPException(400, str(e)[:400]) from None
            finally:
                p.invalidate()
        return {"ok": True, "agent": name, "result": what}

    # ---------------------------------------------------------------- knowledge graph

    graphs: dict[str, tuple[tuple, dict[str, Any]]] = {}

    def project_graph(p: Project, refresh: bool = False) -> dict[str, Any]:
        """The project's knowledge graph, rebuilt when its discovery.json or crucible.yaml changes (or on refresh)."""
        from .discover import build_plan, discover
        from .discover.graph import build_graph, write_graph
        d = _discovery(p)
        stamp = tuple(f.stat().st_mtime_ns for f in (p.discovery_file, p.path) if f.exists())
        cached = graphs.get(p.id)
        if cached and cached[0] == stamp and not refresh:
            return cached[1]
        saved = p.root / "knowledge-graph.json"  # written by the import: reading it beats rebuilding a big repo's graph
        fresh = saved.is_file() and not refresh and d is not None and saved.stat().st_mtime_ns >= max(stamp, default=0)
        if fresh:
            g = json.loads(saved.read_text(encoding="utf-8"))
            codebase = Path(p.codebase) if p.codebase else Path(d.repo.root)
        elif d is not None:
            codebase = Path(p.codebase) if p.codebase else Path(d.repo.root)
        else:  # a hand-written project: read its code (no model) to map it
            codebase = Path(p.codebase) if p.codebase else p.root
            d = discover(codebase)
            build_plan(d, codebase)
        if not fresh:
            g = build_graph(d, codebase if codebase.is_dir() else None)
        # which of the project's agents each agent node is, so the viewer can open its page
        cfg = p.cfg
        named = cfg.agents or ({"agent": cfg.agent} if cfg.agent else {})
        for n in g["nodes"]:
            if n["kind"] != "agent":
                continue
            if n["id"].removeprefix("agent:") in named:
                n["project_agent"] = n["id"].removeprefix("agent:")
                continue
            base = Path(n.get("file") or "").name
            hit = next((name for name, spec in named.items() if base and base in (spec.command or "")), None)
            n["project_agent"] = hit or (next(iter(named)) if len(named) == 1 and n.get("included", True) else None)
        try:  # keep a copy in the repository, next to the tests
            if not fresh:
                write_graph(d, codebase, p.root)
        except OSError:
            pass
        graphs[p.id] = (stamp, g)
        return g

    @app.get("/api/graph")
    async def get_graph(refresh: bool = False, p: Project = Depends(current)) -> dict[str, Any]:
        return await asyncio.to_thread(project_graph, p, refresh)

    @app.get("/api/graph.html")
    async def get_graph_html(refresh: bool = False, p: Project = Depends(current)) -> HTMLResponse:
        from .discover.graph import viewer_html
        return HTMLResponse(viewer_html(await asyncio.to_thread(project_graph, p, refresh)))
