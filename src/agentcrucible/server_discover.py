"""API for codebase import (dashboard: Import). Jobs run in the background; the dashboard polls them.

    POST  /api/discover                 {path | git_url, include, use_llm}  -> job
    GET   /api/discover/roots           folders the server may read, with suggestions
    GET   /api/discover/{job}           status, progress and the draft discovery.json
    PATCH /api/discover/{job}           the reviewer's edits and answers -> re-planned draft
    POST  /api/discover/{job}/tools     {agent, tool}: add a tool the smoke run saw but discovery missed (one click),
                                        then review and approve again to draft its tests
    POST  /api/discover/{job}/apply     write the test project, validate, smoke-run, compare with reality, and add it to
                                        the dashboard's projects (agents added by hand earlier are kept)

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
from typing import Any, Callable

import httpx
import yaml
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from .config import ProjectConfig, Scenario
from .discover import apply, build_plan, clone, default_llm, discover, is_git_url
from .discover.plan import OUT_DIR
from .discover.scan import scan
from .discover.schema import Discovery, Entrypoint, Question, Tool
from .discover.synthesize import dump
from .projects import Workspace


class DiscoverRequest(BaseModel):
    path: str | None = None
    git_url: str | None = None
    include: list[str] = Field(default_factory=list)
    use_llm: bool = True
    llm_url: str | None = None  # another OpenAI-compatible server for the description step (key: CRUCIBLE_LLM_API_KEY)
    llm_model: str | None = None
    # "local" (the model server next to AgentCrucible), "openai" or "anthropic": a hosted model is much faster.
    # The key is used for this import only and is never written to disk.
    llm_provider: str | None = None
    llm_api_key: str | None = Field(default=None, repr=False)


class LlmCheck(BaseModel):
    provider: str  # "openai" or "anthropic"
    api_key: str | None = Field(default=None, repr=False)  # empty: the server's OPENAI_API_KEY / ANTHROPIC_API_KEY
    model: str | None = None  # also check this model is available to the key


_MODEL_LISTS: dict[str, tuple[float, dict[str, Any]]] = {}  # sha256(provider, key) -> (when, a successful check)


def check_hosted_llm(req: LlmCheck) -> dict[str, Any]:
    """Is the key accepted, which models can it use, and is `model` one of them? Reads the model list only: no tokens
    are spent. The key is never logged or stored (a successful list is remembered for 5 minutes by its hash)."""
    import hashlib
    env = "ANTHROPIC_API_KEY" if req.provider == "anthropic" else "OPENAI_API_KEY"
    key = (req.api_key or "").strip() or os.environ.get(env, "")
    tag = hashlib.sha256(f"{req.provider}\n{key}".encode()).hexdigest()
    hit = _MODEL_LISTS.get(tag)
    if hit and time.time() - hit[0] < 300:
        out = dict(hit[1])
        out["model_ok"] = (req.model in out["models"]) if req.model else None
        out["key_from"] = "pasted" if (req.api_key or "").strip() else "server"  # same key, maybe from elsewhere
        return out
    out = _check_hosted_llm(req, key, env)
    if out["ok"]:
        _MODEL_LISTS[tag] = (time.time(), out)
    return out


def _check_hosted_llm(req: LlmCheck, key: str, env: str) -> dict[str, Any]:
    out: dict[str, Any] = {"ok": False, "models": [], "model_ok": None, "key_from": "pasted" if (req.api_key or "").strip()
                           else "server" if key else None, "error": None}
    if not key:
        out["error"] = f"No key: paste one, or set {env} in .env and restart the backend."
        return out
    try:
        if req.provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=key, timeout=15, max_retries=1)
            listed = list(client.models.list(limit=100))
            out["models"] = [m.id for m in listed]
            out["labels"] = {m.id: getattr(m, "display_name", None) or m.id for m in listed}  # "Claude Opus 5.5"
            if req.model:
                try:
                    client.models.retrieve(req.model)
                    out["model_ok"] = True
                except anthropic.NotFoundError:
                    out["model_ok"] = False
        elif req.provider == "openai":
            from .discover.synthesize import PROVIDERS
            h = {"Authorization": f"Bearer {key}"}
            r = httpx.get(PROVIDERS["openai"] + "/models", headers=h, timeout=15)
            r.raise_for_status()
            ids = sorted((m.get("id") or "" for m in r.json().get("data", [])), reverse=True)
            out["models"] = [i for i in ids if re.match(r"(gpt-|o\d|chatgpt-)", i)
                             and not re.search(r"audio|realtime|tts|transcribe|image|search|embedding", i)]
            if req.model:
                out["model_ok"] = httpx.get(f"{PROVIDERS['openai']}/models/{req.model}", headers=h, timeout=15).status_code == 200
        else:
            raise HTTPException(400, "provider must be openai or anthropic")
        out["ok"] = True
    except HTTPException:
        raise
    except Exception as e:  # noqa: BLE001 - reported to the page, which says what to fix
        status = getattr(e, "status_code", None) or getattr(getattr(e, "response", None), "status_code", None)
        out["error"] = ("The key was rejected (401): check it's complete and active." if status == 401
                        else "The key isn't allowed to list models (403)." if status == 403
                        else f"Couldn't reach {'Anthropic' if req.provider == 'anthropic' else 'OpenAI'}: {type(e).__name__}")
    return out


class ReviewPatch(BaseModel):
    agents: dict[str, dict[str, Any]] = Field(default_factory=dict)  # id -> {include, name, purpose}
    tools: dict[str, dict[str, Any]] = Field(default_factory=dict)  # name -> {include, effects}
    mcp_servers: dict[str, dict[str, Any]] = Field(default_factory=dict)  # name -> {include, command, url}
    questions: dict[str, str] = Field(default_factory=dict)  # id -> answer
    scenarios: dict[str, dict[str, Any]] = Field(default_factory=dict)  # id -> {include, yaml}
    fixes: dict[str, bool] = Field(default_factory=dict)  # suggested code change id -> accept


class AddTool(BaseModel):
    agent: str
    tool: str


class ApplyRequest(BaseModel):
    smoke: bool = True
    model: str | None = None
    pull_request: bool = False  # also put the tests on a new branch, push it and open a pull request


EFFECTS = {"read-only", "writes data", "destructive", "external call", "reads untrusted text"}


def roots_from_env(cfg: ProjectConfig) -> list[Path]:
    raw = os.environ.get("CRUCIBLE_DISCOVER_ROOTS")
    if raw:
        return [Path(p).expanduser().resolve() for p in raw.split(os.pathsep) if p.strip()]
    return [Path.home().resolve(), cfg.root.resolve().parent]


def path_map() -> list[tuple[str, str]]:
    """Host folders mounted into this container, from CRUCIBLE_PATH_MAP ("D:/code=/import;..."), longest first."""
    pairs = []
    for item in os.environ.get("CRUCIBLE_PATH_MAP", "").split(";"):
        host, sep, inside = item.rpartition("=")
        if sep and host.strip() and inside.strip():
            pairs.append((host.strip().replace("\\", "/").rstrip("/"), inside.strip().rstrip("/")))
    return sorted(pairs, key=lambda hp: -len(hp[0]))


def to_server_path(raw: str) -> str:
    """A path as typed on the host (D:\\code\\repo) -> the same folder inside the container (/import/repo)."""
    norm = raw.strip().strip('"').replace("\\", "/")
    for host, inside in path_map():
        windows = bool(re.match(r"[A-Za-z]:/", host))
        a, b = (norm.lower(), host.lower()) if windows else (norm, host)
        if a == b or a.startswith(b + "/"):
            return inside + norm[len(host):]
    return raw.strip().strip('"')


def looks_like_host_path(raw: str) -> bool:
    """A Windows path (C:\\... or \\\\server\\share) given to a server that runs on Linux, i.e. in a container."""
    return bool(re.match(r"\s*([A-Za-z]:[\\/]|\\\\)", raw)) and os.name != "nt"


def slim(data: dict[str, Any]) -> dict[str, Any]:
    """The discovery for the review page: only the facts something on the page points at (a big repository has
    thousands, mostly environment variables and entry points, which made every response megabytes)."""
    facts = data.get("facts") or {}
    used: set[str] = set()

    def walk(x: Any) -> None:
        if isinstance(x, str):
            if x in facts:
                used.add(x)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
        elif isinstance(x, list):
            for v in x:
                walk(v)

    walk({k: v for k, v in data.items() if k != "facts"})
    return {**data, "facts": {k: v for k, v in facts.items() if k in used}}


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
                for other in d.questions:  # its other questions (how to start it…) no longer matter
                    if other is not q and other.about == q.about and not other.answer and other.id not in answers:
                        other.answer = "(left out)"
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
            elif s and a and not a.startswith(("/", "\\")) and ".." not in a.replace("\\", "/").split("/"):
                s.schema_files = list(dict.fromkeys([*s.schema_files, a.replace("\\", "/")]))  # a dump or migrations, in the repo
        elif kind == "prompt" and (ag := d.agent(key)):
            note = ("Tests need a fixed copy of the prompt: make the code read it from a setting or file when one is set, "
                    "so `crucible run -e` can pin it.")
            ag.notes = [n for n in ag.notes if n != note] + ([note] if a.lower().startswith("no") else [])
        elif kind == "auth" and (ag := d.agent(key)):
            ag.auth_env = a if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", a) else None
        elif kind == "vector":
            v = next((x for x in d.vector_stores if x.id == key), None)
            if v:
                v.test_with = "live" if "live" in a.lower() else "snapshot" if "snapshot" in a.lower() else "mock"
        elif kind == "mcp":
            s = next((x for x in d.mcp_servers if x.name == key), None)
            if s and a:
                s.command = a


def keep_hand_added(d: Discovery, out: Path) -> list[str]:
    """Carry agents added by hand (and their scenarios) from the project already written at `out` into a re-import."""
    f = out / "discovery.json"
    if not f.is_file():
        return []
    try:
        old = Discovery.model_validate_json(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 - an unreadable old file just means nothing to keep
        return []
    kept = []
    for ag in old.agents:
        if ag.added_by_hand and d.agent(ag.id) is None:
            d.agents.append(ag)
            d.scenarios += [s for s in old.scenarios if s.agent == ag.id and s.edited]
            kept.append(ag.id)
    return kept


def archive_old_runs(out: Path) -> str | None:
    """A repository imported again as a new project starts with no history: the runs an earlier project left in
    agent-tests/.crucible/runs move to .crucible/runs-archive/<when>. Returns the old project's name, if any."""
    import datetime as dt
    import shutil
    runs = out / ".crucible" / "runs"
    if not runs.is_dir() or not any(runs.iterdir()):
        return None
    name = None
    try:
        name = (yaml.safe_load((out / "crucible.yaml").read_text(encoding="utf-8")) or {}).get("project")
    except (OSError, yaml.YAMLError):
        pass
    dest = out / ".crucible" / "runs-archive" / dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(runs), str(dest))
    return name


def register(app: FastAPI, ws: Workspace, lock: asyncio.Lock, index_runs: Callable[[Any], None],
             forget_runs: Callable[[str], Any] = lambda _project: None) -> None:
    jobs: dict[str, dict[str, Any]] = {}
    cfg: ProjectConfig = ws.home.cfg  # imports use the server's model settings
    work = cfg.root / ".crucible" / "imports"

    # imports approved before projects existed (or while the list was lost) still show up as projects
    for f in sorted(work.glob("*.json")) if work.is_dir() else []:
        try:
            old = json.loads(f.read_text(encoding="utf-8"))
            out = Path(((old.get("result") or {}).get("out")) or "")
            if old.get("status") == "applied" and (out / "crucible.yaml").is_file() and ws.for_path(out / "crucible.yaml") is None:
                ws.register(out / "crucible.yaml", "import", codebase=old.get("root") or None, job=old.get("id"))
        except Exception:  # noqa: BLE001 - a stale or broken job file is skipped
            continue

    def save(j: dict[str, Any]) -> None:
        """Keep the job on disk so a server restart doesn't lose a review in progress."""
        j.pop("graph", None)  # the map changed: the knowledge graph is rebuilt on its next request
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
                "discovery": slim(dump(d)) if d is not None else None, "started": j["started"],
                "phase_started": j.get("phase_started") or j["started"],
                "describing": j.get("describing")}  # a model is still writing descriptions in the background

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
        return {"roots": [str(r) for r in roots], "suggestions": list(dict.fromkeys(suggestions))[:30],
                "mounted": [{"host": h, "path": i} for h, i in path_map()]}

    def pick_llm(req: DiscoverRequest, probe: bool = True) -> tuple[str | None, str | None, str | None, str]:
        """(base url, model, provider, api key) for the description step."""
        from .discover.synthesize import CLAUDE_DEFAULT_MODEL, PROVIDERS
        if not req.use_llm:
            return None, None, None, ""
        if req.llm_provider == "anthropic":
            key = req.llm_api_key or os.environ.get("ANTHROPIC_API_KEY", "")
            return PROVIDERS["anthropic"], req.llm_model or CLAUDE_DEFAULT_MODEL, "anthropic", key
        if req.llm_provider == "openai":
            key = req.llm_api_key or os.environ.get("OPENAI_API_KEY", "")
            return req.llm_url or PROVIDERS["openai"], req.llm_model, "openai", key
        if not probe:
            return req.llm_url or cfg.llm.upstream_base_url, req.llm_model, None, cfg.llm.api_key
        url, model = default_llm(req.llm_url or cfg.llm.upstream_base_url, req.llm_model)
        return url, model, None, req.llm_api_key or cfg.llm.api_key

    def check_llm(req: DiscoverRequest) -> None:
        if not req.use_llm or req.llm_provider not in ("openai", "anthropic"):
            return
        env = "ANTHROPIC_API_KEY" if req.llm_provider == "anthropic" else "OPENAI_API_KEY"
        if not (req.llm_api_key or os.environ.get(env)):
            raise HTTPException(400, f"paste an API key for {'Claude' if req.llm_provider == 'anthropic' else 'OpenAI'} "
                                     f"(or set {env} for the server)")
        if req.llm_provider == "openai" and not req.llm_model:
            raise HTTPException(400, "name the OpenAI model to use")

    def check_path(raw: str) -> Path:
        root = Path(to_server_path(raw)).expanduser()
        if not root.is_dir():
            readable = ", ".join(map(str, roots_from_env(cfg)))
            if looks_like_host_path(raw):  # a Windows path, but the server runs in a (Linux) container
                raise HTTPException(400, f"{raw.strip()} isn't inside this container, which can only read {readable}. Mount the "
                                         "folder that holds it: put CRUCIBLE_IMPORT_DIR=<that folder> in .env and run "
                                         "`docker compose up -d backend`, then paste the same path again.")
            raise HTTPException(400, f"{raw.strip()} is not a folder this server can see (it can read {readable})")
        if not allowed(root):
            raise HTTPException(403, "that folder is outside CRUCIBLE_DISCOVER_ROOTS: " + os.pathsep.join(map(str, roots_from_env(cfg))))
        return root

    @app.post("/api/llm/models")
    async def llm_models(req: LlmCheck) -> dict[str, Any]:
        """Check a hosted model key (and model) for the import's descriptions, and list the models it can use."""
        return await asyncio.to_thread(check_hosted_llm, req)

    @app.post("/api/discover/preview")
    async def preview_discover(req: DiscoverRequest) -> dict[str, Any]:
        """What a scan would read and skip, and which model would describe it. Reads names only, no file contents."""
        if not req.path:
            raise HTTPException(400, "give a folder path (a Git URL is previewed after cloning)")
        root = check_path(req.path)
        inv = await asyncio.to_thread(scan, root, req.include or None)
        url, model, provider, _ = await asyncio.to_thread(pick_llm, req, req.llm_provider not in ("openai", "anthropic"))
        return {"root": str(root), "files": len(inv.files), "languages": inv.languages(),
                "skipped": dict(sorted(inv.skip_reasons.items(), key=lambda kv: -kv[1])),
                "secrets_skipped": len(inv.skipped_secret),
                "model": {"url": url, "model": model} if url and model else None,
                "hosted": bool(url and not re.search(r"localhost|127\.0\.0\.1|\bmodels\b|ollama|host\.docker\.internal", url))}

    @app.post("/api/discover", status_code=202)
    async def start_discover(req: DiscoverRequest) -> dict[str, Any]:
        if bool(req.path) == bool(req.git_url):
            raise HTTPException(400, "give a folder path or a git URL")
        if req.git_url and not is_git_url(req.git_url):
            raise HTTPException(400, "not a git URL (https://, ssh://, git@ or file://)")
        root = check_path(req.path) if req.path else None
        check_llm(req)
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
                url, model, provider, key = pick_llm(req)
                if req.use_llm and not url:
                    say("No model server answered, so descriptions come from the code only")
                # the map comes from the code alone; the model's descriptions follow in the background, so a slow
                # local model never holds up the review
                d = discover(r, include=req.include or None, source=req.git_url, progress=say)
                build_plan(d, r)
                say(f"Drafted {len(d.plans)} connection plans and {len(d.scenarios)} scenarios")
                j["discovery"] = d
                j["status"] = "review"
            except Exception as e:  # noqa: BLE001
                j["status"], j["error"] = "failed", f"{type(e).__name__}: {e}"
                say(j["error"])
                save(j)
                return
            save(j)
            try:  # the graph tab opens instantly later instead of building for half a minute on a big repository
                from .discover.graph import build_graph
                j["graph"] = build_graph(d, r)
            except Exception:  # noqa: BLE001 - built on request instead
                pass
            if url and model:
                describe(j, d, url, model, say, provider, key)

        def describe(j: dict[str, Any], d: Discovery, url: str, model: str, say: Callable[[str], None],
                     provider: str | None, key: str) -> None:
            """Ask the model for descriptions on a copy, then merge what the reviewer hasn't changed meanwhile."""
            from .discover.synthesize import PROVIDERS, enrich, enrich_batches
            batches = enrich_batches(d, provider in PROVIDERS)
            n_tools = sum(len(b["tools"]) for b in batches)
            j["describing"] = {"model": model, "requests": len(batches)}
            say(f"Review ready. {model} is describing {len(d.agents)} agents and {n_tools} tools in the background "
                f"({len(batches)} request{'s' if len(batches) > 1 else ''}); the review fills in as answers arrive")
            copy = d.model_copy(deep=True)
            before = {a.id: a.purpose for a in copy.agents}
            asked = len(copy.questions)
            try:
                enrich(copy, url, model, key, progress=say, provider=provider)
            except Exception as e:  # noqa: BLE001 - the map stands without descriptions
                d.synthesis = {"model": model, "used": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
                say(f"Descriptions skipped: {d.synthesis['error']}")
            else:
                changed = 0
                for a in copy.agents:
                    live = d.agent(a.id)
                    if live and a.purpose != before.get(a.id) and live.purpose == before.get(a.id):
                        live.purpose, changed = a.purpose, changed + 1
                for t in copy.tools:
                    live_t = d.tool(t.name)
                    if live_t and t.description and not live_t.description:
                        live_t.description, changed = t.description, changed + 1
                for q in copy.questions[asked:]:
                    q.id = f"q{len(d.questions) + 1}"
                    d.questions.append(q)
                    changed += 1
                d.synthesis = copy.synthesis
                failed = len(copy.synthesis.get("failed") or [])
                say(f"Descriptions done: {changed} added" + (f", {failed} request{'s' if failed > 1 else ''} timed out or failed" if failed else ""))
            j["describing"] = None
            save(j)
            try:  # with the new descriptions in it
                from .discover.graph import build_graph
                j["graph"] = build_graph(d, Path(j["root"]) if j.get("root") else None)
            except Exception:  # noqa: BLE001 - built on request instead
                pass

        save(j)
        threading.Thread(target=run, daemon=True).start()
        return view(j)

    @app.get("/api/discover/{jid}")
    async def get_discover(jid: str) -> dict[str, Any]:
        return view(job(jid))

    @app.get("/api/discover/{jid}/graph")
    async def discover_graph(jid: str) -> dict[str, Any]:
        """The knowledge graph of what the scan found (before anything is written)."""
        from .discover.graph import build_graph
        j = job(jid)
        if j.get("discovery") is None:
            raise HTTPException(409, "the scan hasn't finished")
        if j.get("graph") is None:  # big repositories take a while: built once per version of the map
            j["graph"] = await asyncio.to_thread(build_graph, j["discovery"], Path(j["root"]) if j.get("root") else None)
        return j["graph"]

    @app.get("/api/discover/{jid}/graph.html")
    async def discover_graph_html(jid: str) -> HTMLResponse:
        from .discover.graph import viewer_html
        return HTMLResponse(viewer_html(await discover_graph(jid)))

    @app.get("/api/discover/{jid}/reality")
    async def discover_reality(jid: str) -> dict[str, Any]:
        """The discovery vs reality report of the last apply (404 until a smoke run has finished)."""
        j = job(jid)
        rep = (j.get("result") or {}).get("reality")
        if rep is None:
            raise HTTPException(404, "no smoke run yet: approve the import first")
        return rep

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
                if "mock" in ch:
                    t.mock = None if ch["mock"] is None else bool(ch["mock"])
        for name, ch in patch.mcp_servers.items():
            s = next((x for x in d.mcp_servers if x.name == name), None)
            if s:
                for k in ("include", "command", "url"):
                    if k in ch:
                        setattr(s, k, ch[k])
        answer_questions(d, patch.questions)
        for sid, ch in patch.scenarios.items():
            s = next((x for x in d.scenarios if x.id == sid), None)
            if s and isinstance(ch.get("yaml"), str) and ch["yaml"] != s.yaml:
                try:
                    data = yaml.safe_load(ch["yaml"])
                    Scenario.model_validate(data)
                except Exception as e:  # noqa: BLE001
                    raise HTTPException(422, f"{sid}: not a valid scenario: {str(e)[:300]}") from None
                if data.get("id") != sid:
                    raise HTTPException(422, f"{sid}: keep `id: {sid}` (drafts are matched by id)")
                s.yaml, s.edited = ch["yaml"], True
        for p in d.plans:
            for fx in p.fixes:
                if fx.id in patch.fixes:
                    fx.accept = bool(patch.fixes[fx.id])
        keep = {s.id: s.include for s in d.scenarios}
        keep.update({sid: bool(ch["include"]) for sid, ch in patch.scenarios.items() if "include" in ch})

        def replan() -> dict[str, Any]:  # off the event loop: a big repository takes seconds, other requests go on
            build_plan(d, Path(j["root"]))
            for s in d.scenarios:
                s.include = keep.get(s.id, s.include)
            save(j)
            return view(j)

        return await asyncio.to_thread(replan)

    @app.post("/api/discover/{jid}/tools")
    async def add_observed_tool(jid: str, body: AddTool) -> dict[str, Any]:
        """Add a tool the smoke run saw an agent call but discovery didn't find; drafts its tests on the next approve."""
        j = job(jid)
        d: Discovery | None = j.get("discovery")
        if d is None or j["status"] not in ("applied", "apply_failed"):
            raise HTTPException(409, "add tools after a smoke run")
        ag = d.agent(body.agent)
        if ag is None:
            raise HTTPException(404, f"no agent {body.agent!r}")
        rep = (j.get("result") or {}).get("reality") or {}
        finding = next((f for f in rep.get("findings", []) if f.get("kind") == "unexpected_tool"
                        and f.get("agent") == body.agent and f.get("tool") == body.tool), None)
        if finding is None:
            raise HTTPException(400, "only tools the smoke run saw this agent call can be added this way")
        server = next((m.name for m in d.mcp_servers if body.tool in m.tools), None)
        t = d.tool(body.tool)
        if t is None:
            t = Tool(name=body.tool, kind="mcp" if server else "in-process", server=server, confidence="medium",
                     description=f"Seen in the smoke run: {finding.get('detail', '')}".strip())
            d.tools.append(t)
        t.include = True
        if ag.id not in t.agents:
            t.agents.append(ag.id)
        if body.tool not in ag.tools:
            ag.tools.append(body.tool)
        if not t.effects and not any(q.about == f"tool:{t.name}" for q in d.questions):
            d.questions.append(Question(id=f"q{len(d.questions) + 1}", about=f"tool:{t.name}", suggested="read-only",
                                        options=["read-only", "writes data", "destructive"],
                                        text=f"`{t.name}` showed up in the smoke run. Does it change anything?"))
        rep["findings"] = [f for f in rep.get("findings", []) if f is not finding]
        build_plan(d, Path(j["root"]))
        j["status"] = "review"
        j["progress"].append({"t": round(time.time() - j["started"], 1),
                              "message": f"Added `{t.name}` to {ag.name} from the smoke run; approve again to write its tests"})
        save(j)
        return view(j)

    @app.post("/api/discover/{jid}/smoke", status_code=202)
    async def smoke_again(jid: str) -> dict[str, Any]:
        """After fixing what the connection check found (dependencies, settings): check again and smoke-run."""
        from .discover.apply import smoke_and_report
        j = job(jid)
        d: Discovery | None = j.get("discovery")
        if d is None or j["status"] not in ("applied", "apply_failed") or not (j.get("result") or {}).get("out"):
            raise HTTPException(409, "approve the import first")
        result = dict(j["result"])
        j["status"], j["phase_started"] = "applying", time.time()

        def say(msg: str) -> None:
            j["progress"].append({"t": round(time.time() - j["started"], 1), "message": msg})

        async def run() -> None:
            async with lock:
                try:
                    out = Path(result["out"])
                    cfg = ws.home.cfg
                    result.update(await asyncio.to_thread(
                        smoke_and_report, d, Path(j["root"]), out, model=cfg.model, progress=say,
                        on_episode=lambda res: say(f"{'✓' if res.passed else '✗'} {res.scenario_id}")))
                    proj = ws.for_path(out / "crucible.yaml")
                    if proj is not None:
                        proj.invalidate()
                        await asyncio.to_thread(index_runs, proj)
                    j["result"], j["status"] = result, "applied"
                except Exception as e:  # noqa: BLE001
                    j["result"], j["status"], j["error"] = result, "applied", f"{type(e).__name__}: {e}"
                    say(j["error"])
                save(j)

        save(j)
        j["task"] = asyncio.create_task(run())  # kept on the job, like an apply's, so it isn't garbage-collected
        return view(j)

    @app.post("/api/discover/{jid}/apply", status_code=202)
    async def apply_discover(jid: str, req: ApplyRequest) -> dict[str, Any]:
        j = job(jid)
        d: Discovery | None = j.get("discovery")
        if d is None or j["status"] in ("scanning", "applying"):
            raise HTTPException(409, "not ready to apply")
        if not any(a.include for a in d.agents):
            raise HTTPException(400, "include at least one agent")
        j["status"], j["phase_started"] = "applying", time.time()
        j["result"] = j["error"] = None

        def say(msg: str) -> None:
            j["progress"].append({"t": round(time.time() - j["started"], 1), "message": msg})

        def on_episode(res: Any) -> None:
            say(f"{'✓' if res.passed else '✗'} {res.scenario_id}")

        async def run() -> None:
            async with lock:  # shares the model server with dashboard runs
                try:
                    root = Path(j["root"])
                    out = root / OUT_DIR
                    if (out / "crucible.yaml").is_file() and ws.for_path(out / "crucible.yaml") is None:
                        old = await asyncio.to_thread(archive_old_runs, out)  # a new project: no inherited history
                        if old:
                            await asyncio.to_thread(forget_runs, old)
                            say("Earlier runs of this folder were archived to agent-tests/.crucible/runs-archive/")
                    kept = keep_hand_added(d, root / OUT_DIR)
                    if kept:
                        build_plan(d, root)
                        say(f"Kept {len(kept)} agents added by hand: {', '.join(kept)}")
                    result = await asyncio.to_thread(
                        apply, d, root, None, model=req.model or cfg.model, upstream=cfg.llm.upstream_base_url,
                        smoke=req.smoke, progress=say, on_episode=on_episode)
                    if req.pull_request:
                        from .discover.pr import PullRequestError, for_apply
                        try:
                            pr = await asyncio.to_thread(for_apply, d, root, result)
                            result["pull_request"] = pr
                            say(f"Pull request: {pr['pr_url'] or pr['compare_url'] or 'branch ' + pr['branch']}"
                                + (f" ({pr['note']})" if pr["note"] else ""))
                        except PullRequestError as e:
                            result["pull_request"] = {"error": str(e)}
                            say(f"Pull request not opened: {e}")
                    proj = ws.register(Path(result["out"]), "import", codebase=str(root), job=jid)
                    await asyncio.to_thread(index_runs, proj)  # the smoke run shows up in the project's runs
                    result["project"] = proj.id
                    say(f"Added to the dashboard as project {proj.cfg.project}")
                    j["result"], j["status"] = result, "applied"
                except Exception as e:  # noqa: BLE001
                    j["status"], j["error"] = "apply_failed", f"{type(e).__name__}: {e}"
                    say(j["error"])
                save(j)

        save(j)
        task = asyncio.create_task(run())
        j["task"] = task
        return view(j)
