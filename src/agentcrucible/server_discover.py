"""API for codebase import (dashboard: Import). Jobs run in the background; the dashboard polls them.

    POST  /api/discover                 {path | git_url, include, use_llm}  -> job
    GET   /api/discover/roots           folders the server may read, with suggestions
    GET   /api/discover/{job}           status, progress and the draft discovery.json
    PATCH /api/discover/{job}           the reviewer's edits and answers -> re-planned draft
    POST  /api/discover/{job}/apply     write the test project, validate, smoke-run, compare with reality

Only folders under CRUCIBLE_DISCOVER_ROOTS (os.pathsep-separated; default: the user's home folder and the folder
above this project) can be read. Nothing is written until `apply`.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .config import ProjectConfig
from .discover import apply, build_plan, clone, default_llm, discover, is_git_url
from .discover.schema import Discovery, Entrypoint
from .discover.synthesize import dump


class DiscoverRequest(BaseModel):
    path: str | None = None
    git_url: str | None = None
    include: list[str] = Field(default_factory=list)
    use_llm: bool = True


class ReviewPatch(BaseModel):
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)  # id -> {include, name, purpose}
    tools: dict[str, dict[str, Any]] = Field(default_factory=dict)  # name -> {include, effects}
    mcp_servers: dict[str, dict[str, Any]] = Field(default_factory=dict)  # name -> {include, command, url}
    questions: dict[str, str] = Field(default_factory=dict)  # id -> answer
    scenarios: dict[str, dict[str, Any]] = Field(default_factory=dict)  # id -> {include}


class ApplyRequest(BaseModel):
    smoke: bool = True
    model: str | None = None


EFFECTS = {"read-only", "writes data", "destructive", "external call", "reads untrusted text"}


def roots_from_env(cfg: ProjectConfig) -> list[Path]:
    raw = os.environ.get("CRUCIBLE_DISCOVER_ROOTS")
    if raw:
        return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]
    return [Path.home().resolve(), cfg.root.resolve().parent]


def answer_questions(d: Discovery, answers: dict[str, str]) -> None:
    """Turn the reviewer's answers into changes to the map."""
    for q in d.questions:
        if q.id not in answers:
            continue
        a = answers[q.id].strip()
        q.answer = a
        kind, _, key = (q.about or "").partition(":")
        if kind == "tool" and (t := d.tool(key)):
            chosen = [e for e in re.split(r"\s*,\s*", a) if e in EFFECTS]
            if chosen:
                t.effects = chosen + (["writes data"] if "destructive" in chosen and "writes data" not in chosen else [])
        elif kind == "agent" and (ag := d.agent(key)):
            if a.lower() in ("no", "not an agent", "exclude"):
                ag.include = False
            elif a.lower() in ("yes", "include"):
                ag.include = True
            elif re.fullmatch(r"[\w.]+:[\w.]+", a):  # module:function
                module, obj = a.split(":", 1)
                ag.entrypoint = Entrypoint(kind="code", module=module, object=obj, evidence=ag.entrypoint.evidence)
            elif a:
                ag.entrypoint = Entrypoint(kind="cli", command=a, evidence=ag.entrypoint.evidence)
        elif kind == "datastore":
            s = next((x for x in d.datastores if x.id == key), None)
            if s and re.fullmatch(r"[A-Z][A-Z0-9_]*", a):
                s.url_env = a
        elif kind == "mcp":
            s = next((x for x in d.mcp_servers if x.name == key), None)
            if s and a:
                s.command = a


def register(app: FastAPI, cfg: ProjectConfig, lock: asyncio.Lock) -> None:
    jobs: dict[str, dict[str, Any]] = {}
    work = cfg.root / ".crucible" / "imports"

    def save(j: dict[str, Any]) -> None:
        """Keep the job on disk so a server restart doesn't lose a review in progress."""
        d: Discovery | None = j.get("discovery")
        data = {k: j.get(k) for k in ("id", "status", "source", "progress", "error", "result", "started")}
        data.update(root=str(j.get("root") or ""), discovery=dump(d) if d is not None else None)
        work.mkdir(parents=True, exist_ok=True)
        (work / f"{j['id']}.json").write_text(json.dumps(data, default=str), encoding="utf-8")

    def job(jid: str) -> dict[str, Any]:
        if jid not in jobs:
            f = work / f"{jid}.json"
            if not re.fullmatch(r"[0-9a-f]{10}", jid) or not f.is_file():
                raise HTTPException(404, "unknown import job")
            j = json.loads(f.read_text(encoding="utf-8"))
            j["root"] = Path(j["root"]) if j.get("root") else None
            j["discovery"] = Discovery.model_validate(j["discovery"]) if j.get("discovery") else None
            if j["status"] in ("scanning", "applying"):  # the server restarted mid-way
                j["error"] = "Interrupted by a server restart. " + ("Scan again." if j["status"] == "scanning" else "Approve again to retry.")
                j["status"] = "failed" if j["status"] == "scanning" else "apply_failed"
            jobs[jid] = j
        return jobs[jid]

    def view(j: dict[str, Any]) -> dict[str, Any]:
        d: Discovery | None = j.get("discovery")
        return {"id": j["id"], "status": j["status"], "source": j["source"], "root": str(j.get("root") or ""),
                "progress": j["progress"][-40:], "error": j.get("error"), "result": j.get("result"),
                "discovery": dump(d) if d is not None else None, "started": j["started"]}

    def allowed(path: Path) -> bool:
        p = path.resolve()
        return any(p == r or r in p.parents for r in roots_from_env(cfg))

    @app.get("/api/discover/roots")
    async def discover_roots() -> dict[str, Any]:
        roots = roots_from_env(cfg)
        suggestions: list[str] = []
        for r in roots:
            for cand in [r, *([c for c in sorted(r.iterdir()) if c.is_dir() and not c.name.startswith(".")][:40] if r.is_dir() else [])]:
                if any((cand / m).exists() for m in ("pyproject.toml", "package.json", "requirements.txt", "go.mod", "pom.xml", "setup.py", "Dockerfile", ".git")):
                    suggestions.append(str(cand))
        examples = cfg.root.resolve().parent / "import-demo"
        if examples.is_dir() and allowed(examples):
            suggestions.insert(0, str(examples))
        return {"roots": [str(r) for r in roots], "suggestions": list(dict.fromkeys(suggestions))[:30]}

    @app.post("/api/discover", status_code=202)
    async def start_discover(req: DiscoverRequest) -> dict[str, Any]:
        if bool(req.path) == bool(req.git_url):
            raise HTTPException(400, "give a folder path or a git URL")
        if req.git_url and not is_git_url(req.git_url):
            raise HTTPException(400, "not a git URL (https://, ssh://, git@ or file://)")
        root = None
        if req.path:
            root = Path(req.path).expanduser()
            if not root.is_dir():
                raise HTTPException(400, f"{root} is not a folder this server can see")
            if not allowed(root):
                raise HTTPException(403, "that folder is outside CRUCIBLE_DISCOVER_ROOTS: " + os.pathsep.join(map(str, roots_from_env(cfg))))
        jid = uuid.uuid4().hex[:10]
        j = jobs[jid] = {"id": jid, "status": "scanning", "source": req.git_url or str(root), "root": root,
                         "progress": [], "started": time.time(), "discovery": None}

        def say(msg: str) -> None:
            j["progress"].append({"t": round(time.time() - j["started"], 1), "message": msg})

        def run() -> None:
            try:
                r = root
                if req.git_url:
                    say(f"Cloning {req.git_url}")
                    r = clone(req.git_url, work)
                    j["root"] = r
                url, model = default_llm(cfg.llm.upstream_base_url, None) if req.use_llm else (None, None)
                if req.use_llm and not url:
                    say("No model server answered, so descriptions come from the code only")
                d = discover(r, include=req.include or None, llm_base_url=url, llm_model=model,
                             llm_api_key=cfg.llm.api_key, source=req.git_url, progress=say)
                build_plan(d, r)
                say(f"Drafted {len(d.plans)} connection plans and {len(d.scenarios)} scenarios")
                j["discovery"] = d
                j["status"] = "review"
            except Exception as e:  # noqa: BLE001
                j["status"], j["error"] = "failed", f"{type(e).__name__}: {e}"
                say(j["error"])
            save(j)

        save(j)
        threading.Thread(target=run, daemon=True).start()
        return view(j)

    @app.get("/api/discover/{jid}")
    async def get_discover(jid: str) -> dict[str, Any]:
        return view(job(jid))

    @app.patch("/api/discover/{jid}")
    async def review_discover(jid: str, patch: ReviewPatch) -> dict[str, Any]:
        j = job(jid)
        d: Discovery | None = j.get("discovery")
        if d is None or j["status"] not in ("review", "applied", "apply_failed"):
            raise HTTPException(409, "nothing to review yet")
        for aid, ch in patch.agents.items():
            ag = d.agent(aid)
            if ag:
                for k in ("include", "name", "purpose"):
                    if k in ch:
                        setattr(ag, k, ch[k])
        for name, ch in patch.tools.items():
            t = d.tool(name)
            if t:
                if "include" in ch:
                    t.include = bool(ch["include"])
                if isinstance(ch.get("effects"), list):
                    t.effects = [e for e in ch["effects"] if e in EFFECTS]
        for name, ch in patch.mcp_servers.items():
            s = next((x for x in d.mcp_servers if x.name == name), None)
            if s:
                for k in ("include", "command", "url"):
                    if k in ch:
                        setattr(s, k, ch[k])
        answer_questions(d, patch.questions)
        keep = {s.id: s.include for s in d.scenarios}
        keep.update({sid: bool(ch.get("include", True)) for sid, ch in patch.scenarios.items()})
        build_plan(d, Path(j["root"]))
        for s in d.scenarios:
            s.include = keep.get(s.id, s.include)
        save(j)
        return view(j)

    @app.post("/api/discover/{jid}/apply", status_code=202)
    async def apply_discover(jid: str, req: ApplyRequest) -> dict[str, Any]:
        j = job(jid)
        d: Discovery | None = j.get("discovery")
        if d is None or j["status"] in ("scanning", "applying"):
            raise HTTPException(409, "not ready to apply")
        if not any(a.include for a in d.agents):
            raise HTTPException(400, "include at least one agent")
        j["status"] = "applying"
        j["result"] = j["error"] = None

        def say(msg: str) -> None:
            j["progress"].append({"t": round(time.time() - j["started"], 1), "message": msg})

        def on_episode(res: Any) -> None:
            say(f"{'✓' if res.passed else '✗'} {res.scenario_id}")

        async def run() -> None:
            async with lock:  # shares the model server with dashboard runs
                try:
                    result = await asyncio.to_thread(
                        apply, d, Path(j["root"]), None, model=req.model or cfg.model, upstream=cfg.llm.upstream_base_url,
                        smoke=req.smoke, progress=say, on_episode=on_episode)
                    j["result"], j["status"] = result, "applied"
                except Exception as e:  # noqa: BLE001
                    j["status"], j["error"] = "apply_failed", f"{type(e).__name__}: {e}"
                    say(j["error"])
                save(j)

        save(j)
        task = asyncio.create_task(run())
        j["task"] = task
        return view(j)
