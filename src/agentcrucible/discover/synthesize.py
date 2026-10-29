"""Facts -> agent map.

Assembly is deterministic: agents, tools, servers, data stores and how each agent is started come from facts, so every
claim carries evidence. An optional model pass only writes one-sentence purposes and extra questions, and anything it
says that doesn't cite a fact is dropped.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any, Callable

import httpx

from .. import __version__
from .codefacts import detect_code
from .configs import detect_configs
from .effects import BUILTIN_EFFECTS, merge_effects
from .pyfacts import detect_python
from .scan import Inventory, git_commit, redact, scan
from .schema import (
    Agent,
    Datastore,
    Discovery,
    Entrypoint,
    ExternalApi,
    Fact,
    McpServer,
    ModelRef,
    PromptRef,
    Question,
    RepoInfo,
    Skill,
    Tool,
    VectorStore,
)

Progress = Callable[[str], None]
NOISE_ENV = {"PATH", "HOME", "PORT", "HOST", "DEBUG", "ENV", "LOG_LEVEL", "PYTHONPATH", "NODE_ENV", "TZ"}
DB_URL_ENVS = {"DATABASE_URL", "DB_URL", "POSTGRES_URL", "SQLALCHEMY_DATABASE_URI", "SQLALCHEMY_DATABASE_URL", "PG_URL",
               "POSTGRES_DSN", "DATABASE_DSN", "SQLITE_PATH", "DB_PATH"}


def slug(s: str) -> str:
    out = re.sub(r"[^a-z0-9]+", "-", re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", s).lower()).strip("-")
    return out or "agent"


def _title(s: str) -> str:
    words = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s).replace("_", " ").replace("-", " ").split()
    return " ".join(w if w.isupper() else w.capitalize() for w in words) or s


def _sentence(text: str | None, limit: int = 200) -> str:
    if not text:
        return ""
    t = " ".join(str(text).split())
    m = re.match(r"(.+?[.!?])(\s|$)", t)
    return (m.group(1) if m else t)[:limit]


class Collector:
    def __init__(self) -> None:
        self.facts: dict[str, Fact] = {}

    def add(self, f: Fact) -> str:
        fid = f"f{len(self.facts) + 1}"
        f.id = fid
        self.facts[fid] = f
        return fid

    def of(self, kind: str) -> list[Fact]:
        return [f for f in self.facts.values() if f.kind == kind]


DETECTORS_VERSION = "2026.10.2"  # bump when detector output changes, so drift reports can tell scans apart


def collect(root: Path, include: list[str] | None = None, progress: Progress | None = None) -> tuple[Inventory, Collector]:
    say = progress or (lambda _m: None)
    inv = scan(root, include)
    say(f"Scanned {len(inv.files)} files ({', '.join(f'{n} {lang}' for lang, n in inv.languages().items()) or 'no code'})")
    if inv.skip_reasons or inv.skipped_secret:
        reasons = [f"{n} {why}" for why, n in sorted(inv.skip_reasons.items(), key=lambda kv: -kv[1])]
        say("Skipped " + ", ".join(reasons + ([f"{len(inv.skipped_secret)} secret files (.env, keys)"] if inv.skipped_secret else [])))
    c = Collector()
    detect_python(inv, c.add)
    detect_code(inv, c.add)
    detect_configs(inv, c.add)
    say(f"Found {len(c.of('agent'))} agent candidates, {len(c.of('tool'))} tools, {len(c.of('mcp_server'))} MCP servers")
    return inv, c


# ---------------------------------------------------------------- assembly


def assemble(inv: Inventory, c: Collector, source: str | None = None) -> Discovery:
    d = Discovery(repo=RepoInfo(root=str(inv.root), name=inv.root.name, commit=git_commit(inv.root),
                                languages=inv.languages(), files_scanned=len(inv.files),
                                files_skipped=inv.skipped + len(inv.skipped_secret), source=source),
                  facts=c.facts, generator={"agentcrucible": __version__, "detectors": DETECTORS_VERSION})
    meta: dict[str, dict[str, Any]] = {}  # agent id -> its fact and http entry points (not serialized)
    _tools(d, c)
    _mcp(d, c)
    _agents(d, c, meta)
    _data(d, c)
    _code_access(d)
    _link_tools(d, c, meta)
    _entrypoints(d, c, meta)
    _agent_context(d, meta)
    _questions(d, c, meta)
    d.skills = [Skill(name=f.name, description=f.attrs.get("description", ""), file=f.attrs["file"], evidence=[f.id])
                for f in c.of("skill")]
    d.env_vars = sorted({f.name for f in c.of("env_var")} - NOISE_ENV)
    d.test_cases = [{"input": f.attrs["input"], "expected": f.attrs.get("expected"), "file": f.attrs["file"], "evidence": [f.id]}
                    for f in c.of("test_case")]
    d.repo.frameworks = sorted({a.framework for a in d.agents} | {"mcp" for _ in d.mcp_servers[:1]}
                               | {f.framework for f in c.of("tool") if f.framework not in ("raw", "generic")})
    return d


def _tools(d: Discovery, c: Collector) -> None:
    by_name: dict[str, Tool] = {}
    for f in c.of("tool"):
        a = f.attrs
        kind = "mcp" if a.get("mcp") else "in-process"
        t = by_name.get(f.name)
        if t is None:
            t = by_name[f.name] = Tool(name=f.name, kind=kind, description=_sentence(a.get("description")),
                                       params=a.get("params") or {}, effects=a.get("effects") or [],
                                       confidence="high" if f.framework not in ("raw", "generic") else "medium", evidence=[f.id])
        else:
            t.evidence.append(f.id)
            t.description = t.description or _sentence(a.get("description"))
            t.params = t.params or a.get("params") or {}
            t.effects = merge_effects(t.effects, a.get("effects"))
            if a.get("function") and not t.params:
                t.params = a.get("params") or {}
    d.tools = list(by_name.values())


def _mcp(d: Discovery, c: Collector) -> None:
    servers: dict[str, McpServer] = {}
    var_to_server: dict[tuple[str, str], str] = {}
    for f in c.of("mcp_server"):
        a = f.attrs
        cmd = a.get("command")
        if not cmd and a.get("language") in ("typescript", "javascript"):
            cmd = f"npx tsx {a['file']}"
        if not cmd and a.get("language") == "go":
            cmd = f"go run ./{Path(a['file']).parent.as_posix()}"
        s = servers.setdefault(f.name, McpServer(name=slug(f.name).replace("-", "_"), command=cmd, defined_here=True, evidence=[]))
        if a.get("sdk"):
            s.url = None  # runs inside the agent's own process (Claude Agent SDK): nothing to start
        s.evidence.append(f.id)
        var_to_server[(a.get("file", ""), a.get("var") or "")] = f.name
        for t in a.get("tools") or []:
            if t["name"] not in s.tools:
                s.tools.append(t["name"])
            if not d.tool(t["name"]):
                d.tools.append(Tool(name=t["name"], kind="mcp", server=s.name, description=_sentence(t.get("description")),
                                    params=t.get("params") or {}, effects=t.get("effects") or [], confidence="high", evidence=[f.id]))
    for t_fact in c.of("tool"):  # TypeScript / Go MCP tools: attach to the server defined in the same file
        if not t_fact.attrs.get("mcp"):
            continue
        sname = var_to_server.get((t_fact.attrs.get("file", ""), t_fact.attrs.get("server_var") or "")) or next(
            (name for (file, _), name in var_to_server.items() if file == t_fact.attrs.get("file")), None)
        if sname:
            s = servers[sname]
            if t_fact.name not in s.tools:
                s.tools.append(t_fact.name)
            t = d.tool(t_fact.name)
            if t:
                t.kind, t.server = "mcp", s.name
    for f in c.of("mcp_client"):
        a = f.attrs
        name = slug(a.get("name") or f.name).replace("-", "_")
        if a.get("command") and any(s.command and Path(s.command.split()[-1]).name in a["command"] for s in servers.values()):
            continue  # a client for a server defined in this repository
        if name in {s.name for s in servers.values()}:
            continue
        servers.setdefault(f"client:{name}", McpServer(name=name, command=a.get("command"), url=a.get("url"), defined_here=False,
                                                       evidence=[f.id]))
    d.mcp_servers = list(servers.values())
    for s in d.mcp_servers:
        for tname in s.tools:
            t = d.tool(tname)
            if t:
                t.kind, t.server = "mcp", s.name


def _agents(d: Discovery, c: Collector, meta: dict[str, dict[str, Any]]) -> None:
    facts = c.of("agent")
    edges = c.of("subagent_edge")
    agents: list[Agent] = []
    key_of: dict[str, Agent] = {}  # "file::var" and names -> agent
    used_ids: set[str] = set()

    def new_id(name: str) -> str:
        base = slug(name)
        i, out = 2, base
        while out in used_ids:
            out = f"{base}-{i}"
            i += 1
        used_ids.add(out)
        return out

    yaml_crew = {f.attrs["config_key"]: f for f in facts if f.attrs.get("yaml")}
    # LangChain: AgentExecutor(agent=tool_agent, tools=...) is the agent to test; the runnable it wraps is not separate
    wrapped = {(f.attrs.get("file"), f.attrs["wraps"]) for f in facts if f.attrs.get("wraps")}
    for f in facts:
        a = f.attrs
        if (a.get("file"), a.get("object")) in wrapped:
            continue
        if a.get("yaml") and any(g.attrs.get("config_key") == a["config_key"] and not g.attrs.get("yaml") for g in facts):
            continue  # the Python Agent(config=...) for this YAML entry carries the object; merged below
        model = a.get("model") or {}
        prompt = a.get("prompt") or {}
        desc = a.get("description") or ""
        if a.get("config_key") and a["config_key"] in yaml_crew and not a.get("yaml"):
            y = yaml_crew[a["config_key"]].attrs
            desc = desc or y.get("description", "")
            prompt = prompt or y.get("prompt") or {}
            model = model or y.get("model") or {}
        name = f.name
        ag = Agent(
            id=new_id(name), name=_title(name), framework=f.framework, language=a.get("language", "python"),
            purpose=_sentence(desc) or _sentence(prompt.get("text")),
            model=ModelRef(value=model.get("value"), env=model.get("env"), evidence=[f.id] if model else []),
            system_prompt=PromptRef(file=prompt.get("file"), text=prompt.get("text") or (f"from {prompt['ref']}" if prompt.get("ref") else
                                    f"from ${prompt['env']}" if prompt.get("env") else None), evidence=[f.id] if prompt else []),
            tools=list(dict.fromkeys(a.get("tools") or [])), confidence=a.get("confidence", "medium"), evidence=[f.id],
        )
        meta[ag.id] = {"fact": f}
        agents.append(ag)
        for k in (a.get("object"), a.get("factory"), a.get("function"), a.get("method"), a.get("config_key"), f.name):
            if k:
                key_of.setdefault(f"{a.get('file')}::{k}", ag)
                key_of.setdefault(f"*::{k}", ag)
    # LangGraph: nodes, ToolNode tools and the compiled object
    for e in edges:
        a = e.attrs
        g = key_of.get(f"{a.get('file')}::{a.get('parent_var')}")
        if g is None:
            continue
        g.evidence.append(e.id)
        if a.get("kind") == "compile" and a.get("compiled_as"):
            meta[g.id]["fact"].attrs["compiled_as"] = a["compiled_as"]
            key_of.setdefault(f"{a.get('file')}::{a['compiled_as']}", g)
        for t in a.get("tools") or []:
            if t not in g.tools:
                g.tools.append(t)
        child = a.get("child")
        sub = key_of.get(f"{a.get('file')}::{child}") if child else None
        if sub is not None and sub is not g and sub.id not in g.subagents:
            g.subagents.append(sub.id)
    # crews, workflows, handoffs, sub_agents
    for ag in agents:
        f = meta[ag.id]["fact"]
        for member in f.attrs.get("members") or []:
            key = re.sub(r"^self\.|\(\)$", "", member)
            sub = key_of.get(f"{f.attrs.get('file')}::{key}") or key_of.get(f"*::{key}")
            if sub is not None and sub is not ag and sub.id not in ag.subagents:
                ag.subagents.append(sub.id)
        for sname in f.attrs.get("subagents") or []:  # Claude Agent SDK subagent definitions
            ag.notes.append(f"Defines a subagent `{sname}` (Claude Agent SDK).")
    members = {s for ag in agents for s in ag.subagents}
    for ag in agents:
        f = meta[ag.id]["fact"]
        if ag.id in members:
            parent = next(p for p in agents if ag.id in p.subagents)
            ag.include = False
            ag.notes.append(f"Tested through {parent.name}, which hands work to it.")
        if ag.confidence == "low":
            ag.include = not any(o.confidence != "low" and meta[o.id]["fact"].attrs.get("file") == f.attrs.get("file") for o in agents)
        if f.attrs.get("role") == "graph" and not f.attrs.get("compiled_as"):
            ag.notes.append("The graph is never compiled in this file; the adapter needs the compiled graph.")
    # model fallback: a model call in the same file
    for ag in agents:
        if not ag.model.value and not ag.model.env:
            file = meta[ag.id]["fact"].attrs.get("file")
            m = next((f for f in c.of("model") if f.attrs.get("file") == file and (f.attrs.get("value") or f.attrs.get("env"))), None)
            if m:
                ag.model = ModelRef(value=m.attrs.get("value"), env=m.attrs.get("env"), evidence=[m.id])
    d.agents = agents


def _data(d: Discovery, c: Collector) -> None:
    stores: dict[str, Datastore] = {}
    tables: list[Fact] = []
    for f in c.of("datastore"):
        a = f.attrs
        if a.get("table") or a.get("schema_file") and not a.get("url_env") and f.framework in ("alembic",):
            tables.append(f)
            continue
        env = a.get("url_env")
        sid = "app" if (env in DB_URL_ENVS or (not env and a.get("kind") in ("sqlite", "postgres"))) else slug(env or a.get("kind") or "db")
        s = stores.setdefault(sid, Datastore(id=sid.replace("-", "_"), kind=a.get("kind") or "unknown", url_env=env))
        s.evidence.append(f.id)
        if s.kind == "unknown" and a.get("kind"):
            s.kind = a["kind"]
    for f in tables:
        a = f.attrs
        target = stores.get("app") or (next(iter(stores.values())) if len(stores) == 1 else None)
        if target is None:
            target = stores.setdefault("app", Datastore(id="app", kind=a.get("kind") if a.get("kind") != "unknown" else "unknown",
                                                        url_env=a.get("url_env")))
        if a.get("table"):
            target.tables.setdefault(a["table"], {}).update(a.get("columns") or {})
        if a.get("schema_file") and a["schema_file"] not in target.schema_files:
            target.schema_files.append(a["schema_file"])
        target.url_env = target.url_env or a.get("url_env")
        target.evidence.append(f.id)
    d.datastores = list(stores.values())
    apis: dict[str, ExternalApi] = {}
    for f in c.of("external_api"):
        a = f.attrs
        host = a.get("base_url") and re.sub(r"^https?://", "", a["base_url"]).split("/")[0]
        env = a.get("base_url_env")
        if a.get("queue"):  # named after the queue system, not its broker setting
            aid = a["queue"]
        elif host:
            parts = [p for p in host.split(".") if p not in ("api", "www", "com", "io", "co", "net", "org", "dev", "app", "v1")]
            aid = slug(parts[0] if parts else host).replace("-", "_")
        elif env:
            aid = slug(re.sub(r"_(API_)?(BASE(_URL)?|URL|HOST|ENDPOINT)$", "", env)).replace("-", "_")
        else:
            aid = slug(a.get("sdk") or f.name).replace("-", "_")
        api = apis.setdefault(aid, ExternalApi(id=aid, base_url=a.get("base_url"), base_url_env=env,
                                               kind="queue" if a.get("queue") else "http"))
        api.base_url = api.base_url or a.get("base_url")
        api.base_url_env = api.base_url_env or env
        if a.get("path") and a["path"] not in api.paths:
            api.paths.append(a["path"])
        api.evidence.append(f.id)
    d.external_apis = list(apis.values())
    vs: dict[str, VectorStore] = {}
    for f in c.of("vector_store"):
        v = vs.setdefault(f.name, VectorStore(id=slug(f.name).replace("-", "_"), kind=f.name))
        v.evidence.append(f.id)
    d.vector_stores = list(vs.values())


def _file_of(d: Discovery, fids: list[str]) -> set[str]:
    return {e.file for i in fids if i in d.facts for e in d.facts[i].evidence}


SQL_WRITE_STMT = re.compile(r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+[\"`]?(\w+)[^\"\n]*", re.I)
SQL_READ_TABLE = re.compile(r"\b(?:FROM|JOIN)\s+[\"`]?(\w+)", re.I)
FILE_READ = re.compile(r"\bopen\([^)]*\)|\.read_text\(|\.read_bytes\(|os\.listdir\(|\.glob\(|\.iterdir\(|readFile(Sync)?\(|fs\.readdir")
FILE_WRITE = re.compile(r"\bopen\([^)]*[\"'][wa]b?\+?[\"']|\.write_text\(|\.write_bytes\(|writeFile(Sync)?\(|appendFile(Sync)?\(")


def _impl_text(d: Discovery, t: Tool, cache: dict[str, list[str]]) -> str:
    """The source of a tool's implementation: the block under each place it was found (a def, a decorator, a branch)."""
    out: list[str] = []
    for fid in t.evidence:
        f = d.facts.get(fid)
        for e in (f.evidence if f else []):
            if e.file not in cache:
                try:
                    cache[e.file] = (Path(d.repo.root) / e.file).read_text(encoding="utf-8", errors="replace").splitlines()
                except OSError:
                    cache[e.file] = []
            lines = cache[e.file][e.line - 1:e.line + 150]
            if not lines:
                continue
            indent = len(lines[0]) - len(lines[0].lstrip())
            block = [lines[0]]
            for ln in lines[1:]:
                if ln.strip() and len(ln) - len(ln.lstrip()) <= indent and not ln.lstrip().startswith(("@", ")", "}", "]")):
                    break
                block.append(ln)
            out.append("\n".join(block))
    joined = "\n".join(out)
    if not re.search(rf"\b(def|function)\s+{re.escape(t.name)}\b|\b{re.escape(t.name)}\s*=\s*(async\s*)?\(", joined):
        # only the schema or registration was recorded: find the implementation by name in the same files
        for file in {e.file for fid in t.evidence if fid in d.facts for e in d.facts[fid].evidence}:
            lines = cache.get(file) or []
            for i, ln in enumerate(lines):
                if re.match(rf"\s*(async\s+)?(def|function)\s+{re.escape(t.name)}\b|\s*(export\s+)?const\s+{re.escape(t.name)}\s*=", ln):
                    indent = len(ln) - len(ln.lstrip())
                    block = [ln]
                    for nxt in lines[i + 1:i + 150]:
                        if nxt.strip() and len(nxt) - len(nxt.lstrip()) <= indent and not nxt.lstrip().startswith((")", "}", "]")):
                            break
                        block.append(nxt)
                    joined += "\n" + "\n".join(block)
                    break
    return joined


def _code_access(d: Discovery) -> None:
    """Which tables each tool writes (for drafted state checks) and whether it touches files on disk."""
    tables = {tb.lower(): s.id for s in d.datastores for tb in s.tables}
    cache: dict[str, list[str]] = {}
    for t in d.tools:
        if t.kind != "in-process":
            continue
        text = _impl_text(d, t, cache)
        if not text:
            continue
        for m in SQL_WRITE_STMT.finditer(text):
            stmt = " ".join(m.group(0).split()).rstrip("'`,;")
            if m.group(1).lower() in tables and stmt not in t.sql_writes and len(t.sql_writes) < 5:
                t.sql_writes.append(stmt)
        for name in {m.group(1).lower() for m in SQL_WRITE_STMT.finditer(text)} | {m.group(1).lower() for m in SQL_READ_TABLE.finditer(text)}:
            if name in tables and f"datastore:{tables[name]}" not in t.touches:
                t.touches.append(f"datastore:{tables[name]}")
        t.files = (["read"] if FILE_READ.search(text) else []) + (["write"] if FILE_WRITE.search(text) else [])
        for v in d.vector_stores:
            if re.search(rf"(?i)\b{re.escape(v.kind)}\b|similarity_search|as_retriever|\.retrieve\(|vector_?store", text) \
                    and f"vector:{v.id}" not in t.touches:
                t.touches.append(f"vector:{v.id}")


def _link_tools(d: Discovery, c: Collector, meta: dict[str, dict[str, Any]]) -> None:
    # Java (Spring AI, LangChain4j): an agent is given tool classes; its tools are their @Tool methods
    for ag in d.agents:
        holders = meta[ag.id]["fact"].attrs.get("tool_holders")
        if holders is not None:
            for f in c.of("tool"):
                if f.attrs.get("language") == "java" and (not holders or f.attrs.get("holder") in holders) and f.name not in ag.tools:
                    ag.tools.append(f.name)
    # pydantic-ai @agent.tool decorators attach to the agent object they decorate
    for f in c.of("tool"):
        var = f.attrs.get("agent_var")
        if var:
            ag = next((a for a in d.agents if meta[a.id]["fact"].attrs.get("object") == var
                       and meta[a.id]["fact"].attrs.get("file") == f.attrs.get("file")), None)
            if ag and f.name not in ag.tools:
                ag.tools.append(f.name)
    # TypeScript: tools: { searchProducts: searchProductsTool } where the tool is defined in another file
    for ag in d.agents:
        for var, key in (meta[ag.id]["fact"].attrs.get("tool_aliases") or {}).items():
            t = d.tool(var)
            if t is not None and key in ag.tools and not d.tool(key):
                t.name = key
    by_norm = {re.sub(r"[^a-z0-9]", "", t.name.lower()): t.name for t in d.tools}
    for ag in d.agents:  # lookupOrder in one file, lookup_order in another
        ag.tools = list(dict.fromkeys(by_norm.get(re.sub(r"[^a-z0-9]", "", tn.lower()), tn) if not d.tool(tn) else tn for tn in ag.tools))
    tool_names = {t.name for t in d.tools}
    for ag in d.agents:
        for tn in ag.tools:
            if tn not in tool_names:
                builtin = tn[:1].isupper() or tn in BUILTIN_EFFECTS
                d.tools.append(Tool(name=tn, kind="builtin" if builtin else "unknown",
                                    description="A built-in tool class from a library." if builtin else "",
                                    effects=BUILTIN_EFFECTS.get(tn) or (["external call", "reads untrusted text", "read-only"]
                                                                        if builtin and re.search(r"search|web|browse|tavily|serp|wiki", tn, re.I) else []),
                                    confidence="low", evidence=list(ag.evidence[:1])))
                tool_names.add(tn)
        files = _file_of(d, ag.evidence)
        ag.mcp_servers = sorted({s.name for s in d.mcp_servers if not s.defined_here and _file_of(d, s.evidence) & files}
                                | {s.name for s in d.mcp_servers if s.defined_here and any(t in s.tools for t in ag.tools)})
    for t in d.tools:
        t.agents = [a.id for a in d.agents if t.name in a.tools]
        files = _file_of(d, t.evidence)
        for s in d.datastores:
            if _file_of(d, s.evidence) & files and set(t.effects) & {"writes data", "destructive", "read-only"}                     and f"datastore:{s.id}" not in t.touches:
                t.touches.append(f"datastore:{s.id}")
        for api in d.external_apis:
            if _file_of(d, api.evidence) & files and "external call" in t.effects:
                t.touches.append(f"api:{api.id}")
    for ag in d.agents:
        tool_files = set().union(*[_file_of(d, t.evidence) for t in d.tools if t.name in ag.tools]) if ag.tools else set()
        files = _file_of(d, ag.evidence) | tool_files
        in_process = [t for t in d.tools if t.name in ag.tools and t.kind == "in-process"]
        by_tool = {x.split(":", 1)[1] for t in d.tools if t.name in ag.tools for x in t.touches if x.startswith("datastore:")}
        ag.datastores = [s.id for s in d.datastores if _file_of(d, s.evidence) & files or s.id in by_tool] or \
            ([d.datastores[0].id] if len(d.datastores) == 1 and in_process else [])
        ag.external_apis = [api.id for api in d.external_apis if _file_of(d, api.evidence) & files]
        if not ag.purpose:
            ag.purpose = f"Uses {', '.join(ag.tools[:4])}{'…' if len(ag.tools) > 4 else ''}." if ag.tools else ""


def _serves(d: Discovery, e: Fact, module: str | None) -> bool:
    """A route serves an agent when it's in the agent's module or its file imports that module (two services that
    both define `run` don't share each other's endpoints)."""
    if not module or e.attrs.get("module") in (None, module):
        return True
    try:
        src = (Path(d.repo.root) / e.evidence[0].file).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return True
    leaf = module.rsplit(".", 1)[-1]
    return bool(re.search(rf"^\s*(from\s+{re.escape(module)}\s+import|import\s+{re.escape(module)}\b|from\s+\S*\s+import\s+.*\b{re.escape(leaf)}\b)",
                          src, re.M))


def _entrypoints(d: Discovery, c: Collector, meta: dict[str, dict[str, Any]]) -> None:
    entries = c.of("entrypoint")
    for ag in d.agents:
        f = meta[ag.id]["fact"]
        a = f.attrs
        names = {x for x in (a.get("object"), a.get("compiled_as"), a.get("factory"), a.get("function"), a.get("method"), a.get("config_key")) if x}
        module = a.get("module")
        http = [e for e in entries if e.attrs.get("kind") == "http" and e.attrs.get("route") and names & set(e.attrs.get("names_used") or [])
                and _serves(d, e, module)]
        obj = a.get("compiled_as") or a.get("object")
        importable = bool(module) and (ag.language == "python" or a.get("exported"))
        if a.get("role") == "loop" or a.get("framework", "").startswith("raw") or a.get("function") and not obj:
            obj = a.get("function") or obj
        if a.get("cls") and a.get("role") == "loop":
            importable = False  # a method on a class we can't construct for you
        if f.framework == "claude-agent-sdk":
            obj = a.get("function")
        if importable and (a.get("factory") or obj):
            factory = bool(a.get("factory")) and not a.get("compiled_as") and not (obj and obj != a.get("factory"))
            ag.entrypoint = Entrypoint(kind="code", module=module, object=a.get("factory") if factory else obj, factory=factory,
                                       evidence=[f.id])
        elif http:
            e = http[0]
            ag.entrypoint = Entrypoint(kind="http", route=e.attrs["route"] if not e.attrs.get("method") else f"{e.attrs['method']} {e.attrs['route']}",
                                       module=e.attrs.get("module"), object=e.attrs.get("app_var"), evidence=[e.id])
        else:
            cli = [e for e in entries if e.attrs.get("kind") == "cli" and names & set(e.attrs.get("names_used") or [])]
            if cli:
                ag.entrypoint = Entrypoint(kind="cli", command=cli[0].attrs.get("command"), evidence=[cli[0].id])
        if http:
            ag.notes.append("Also served over HTTP at " + ", ".join(sorted({x.name for x in http})) + ".")
            meta[ag.id]["http"] = [x.id for x in http]


PROMPT_ANSWERS = ("yes, the live prompt", "no, a fixed copy")
VECTOR_ANSWERS = ("mock the retriever with fixed passages", "use the live store (read-only)")
MEMORY = re.compile(r"\b(MemorySaver|InMemorySaver|SqliteSaver|AsyncSqliteSaver|PostgresSaver|AsyncPostgresSaver|RedisSaver|"
                    r"ConversationBufferMemory|ConversationSummaryMemory|ChatMessageHistory|RedisChatMessageHistory|"
                    r"SQLiteSession|SQLAlchemySession|RedisSession|InMemoryStore|Mem0Memory|mem0|ZepMemory|"
                    r"InMemorySessionService|DatabaseSessionService|checkpointer|chat_history|session_id)\b")
AUTH = re.compile(r"Depends\(\s*\w*(auth|user|token|current|verify|login|api_key|bearer)\w*|login_required|requires_auth|"
                  r"jwt_required|HTTPBearer|OAuth2PasswordBearer|APIKeyHeader|verify_token|[\"']authorization[\"']|"
                  r"authenticate\(|requireAuth|withAuth|getServerSession|auth\(\)", re.I)
PROMPT_SOURCE = re.compile(r"(langfuse\.\w*get_prompt|\.get_prompt\(|hub\.pull\(|promptlayer|humanloop|"
                           r"SELECT\s[^\"']*\bFROM\s+prompts\b|prompts\.find|load_prompt\(|portkey\.prompts)", re.I)
SERVICE_MARKERS = ("pyproject.toml", "package.json", "go.mod", "pom.xml", "build.gradle", "Dockerfile", "setup.py")


def _agent_context(d: Discovery, meta: dict[str, dict[str, Any]]) -> None:
    """Facts about an agent that need its whole file: memory, which service it belongs to, auth on its endpoint and
    prompts loaded from outside the repository."""
    root = Path(d.repo.root)
    cache: dict[str, str] = {}

    def text(file: str) -> str:
        if file not in cache:
            try:
                cache[file] = (root / file).read_text(encoding="utf-8", errors="replace")
            except OSError:
                cache[file] = ""
        return cache[file]

    services: dict[str, str | None] = {}
    for ag in d.agents:
        files = sorted(_file_of(d, ag.evidence))
        src = "\n".join(text(f) for f in files)
        m = MEMORY.search(src)
        if m:
            ag.memory = m.group(1)
            if ag.memory in ("checkpointer", "chat_history", "session_id"):
                ag.memory = {"checkpointer": "a checkpointer", "chat_history": "chat history", "session_id": "sessions"}[ag.memory]
        p = PROMPT_SOURCE.search(src)
        if p:
            meta[ag.id]["prompt_source"] = p.group(1).strip()[:60]
            ag.notes.append(f"Its prompt is loaded at run time (`{meta[ag.id]['prompt_source']}`): test prompt changes with "
                            "`crucible run -e <SETTING>=<value>` overrides.")
        for fid in meta[ag.id].get("http", []):
            e = d.facts[fid].evidence[0]
            block = "\n".join(text(e.file).splitlines()[max(0, e.line - 4):e.line + 25])
            if AUTH.search(block):
                meta[ag.id]["auth"] = [fid]
                break
        if files:
            folder = Path(files[0]).parent
            if str(folder) not in services:
                svc = None
                for cand in [folder, *folder.parents]:
                    if str(cand) in (".", "") or cand == Path("."):
                        break
                    if any((root / cand / mk).exists() for mk in SERVICE_MARKERS):
                        svc = cand.as_posix()
                        break
                services[str(folder)] = svc
            ag.service = services[str(folder)]
    if len({a.service for a in d.agents}) < 2:  # one service: nothing to group
        for a in d.agents:
            a.service = None
    names = [a.name for a in d.agents]
    for a in d.agents:  # two services that both call it "Run": "Billing · Run"
        if a.service and names.count(a.name) > 1:
            a.name = f"{Path(a.service).name.replace('-', ' ').replace('_', ' ').title()} · {a.name}"


def _questions(d: Discovery, c: Collector, meta: dict[str, dict[str, Any]]) -> None:
    qs: list[Question] = []

    def q(text: str, about: str, evidence: list[str], suggested: str | None = None, options: list[str] | None = None) -> None:
        qs.append(Question(id=f"q{len(qs) + 1}", text=text, about=about, evidence=evidence, suggested=suggested, options=options or []))

    for ag in d.agents:
        if not ag.include and ag.confidence != "low":
            continue
        if ag.confidence == "low":
            q(f"Is `{ag.name}` an agent you want to test? It was found only by the generic fallback.", f"agent:{ag.id}",
              ag.evidence, "yes", ["yes", "no"])
        if ag.entrypoint.kind == "unknown":
            q(f"How can AgentCrucible start `{ag.name}`? Give a function to import (module:function) or a command.",
              f"agent:{ag.id}", ag.evidence, None)
        if len(meta[ag.id].get("http", [])) > 1:
            names = [d.facts[i].name for i in meta[ag.id]["http"]]
            q(f"`{ag.name}` is reachable at several endpoints. Which one is the main entry point?", f"agent:{ag.id}",
              meta[ag.id]["http"], names[0], names)
    for t in d.tools:
        if t.agents and not t.effects and t.kind != "builtin":
            q(f"Does the tool `{t.name}` change anything?", f"tool:{t.name}", t.evidence, None,
              ["read-only", "writes data", "destructive"])
    for s in d.datastores:
        if not s.url_env and s.tables:
            q(f"Which setting holds the database URL for the tables {', '.join(list(s.tables)[:4])}?", f"datastore:{s.id}",
              s.evidence, "DATABASE_URL")
    for v in d.vector_stores:
        q(f"How should tests get documents for the {v.kind} vector store?", f"vector:{v.id}", v.evidence,
          VECTOR_ANSWERS[0], list(VECTOR_ANSWERS))
    for s in d.datastores:
        if not s.tables and not s.schema_files:
            q(f"The database `{s.id}` has no schema files or models in the repository. Point to a schema dump or "
              "migrations folder (a path in the repository) so tests can build it.", f"datastore:{s.id}", s.evidence, None)
    for ag in d.agents:
        m = meta[ag.id]
        if ag.include and m.get("auth"):
            q(f"The endpoint of `{ag.name}` needs a signed-in user. Which environment variable will hold a test token?",
              f"auth:{ag.id}", m["auth"], "APP_TEST_TOKEN")
        if ag.include and m.get("prompt_source"):
            q(f"`{ag.name}` loads its prompt at run time (`{m['prompt_source']}`). Should tests use the live prompt?",
              f"prompt:{ag.id}", ag.evidence, PROMPT_ANSWERS[0], list(PROMPT_ANSWERS))
    for s in d.mcp_servers:
        sdk = any(d.facts[i].attrs.get("sdk") for i in s.evidence if i in d.facts)
        if s.defined_here and not s.command and not sdk:
            q(f"How is the MCP server `{s.name}` started? (e.g. `python path/to/server.py`)", f"mcp:{s.name}", s.evidence, None)
    d.questions = qs


# ---------------------------------------------------------------- optional model pass


ENRICH_PROMPT = (
    "You review an automatically generated map of the AI agents in a code repository. "
    "Return JSON only, with this shape:\n"
    '{"agents": {"<id>": "<one sentence: what the agent does, for a reviewer>"}, '
    '"tools": {"<name>": "<one sentence>"}, '
    '"questions": [{"about": "agent:<id>|tool:<name>", "text": "<question>", "evidence": ["<fact id>"]}]}\n'
    "Rules: only describe what the evidence shows; skip anything you are unsure about; at most 5 questions, each "
    "citing at least one fact id from the input.\n\n"
)
BATCH_TOOLS, BATCH_AGENTS = 40, 12


def _cache_dir() -> Path:
    return Path(os.environ.get("CRUCIBLE_CACHE_DIR") or Path.home() / ".cache" / "agentcrucible") / "synthesis"


def enrich_batches(d: Discovery) -> list[dict[str, Any]]:
    """What will be sent: agents and tools with redacted snippets, grouped by module so each request stays small
    (large repositories get several requests whose answers are merged)."""
    def src(fid: str) -> dict[str, Any]:
        e = d.facts[fid].evidence[0]
        return {"fact": fid, "file": e.file, "line": e.line, "snippet": redact(e.snippet)[:300]}

    agents = [{"id": a.id, "name": a.name, "framework": a.framework, "tools": a.tools[:20], "current": a.purpose,
               "evidence": [src(fid) for fid in a.evidence[:2] if fid in d.facts]} for a in d.agents]
    tools = [{"name": t.name, "current": t.description, "effects": t.effects,
              "evidence": [src(t.evidence[0])] if t.evidence and t.evidence[0] in d.facts else []} for t in d.tools]
    by_module: dict[str, list[dict[str, Any]]] = {}
    for t in tools:
        by_module.setdefault(t["evidence"][0]["file"] if t["evidence"] else "", []).append(t)
    tool_batches: list[list[dict[str, Any]]] = [[]]
    for group in by_module.values():
        if tool_batches[-1] and len(tool_batches[-1]) + len(group) > BATCH_TOOLS:
            tool_batches.append([])
        tool_batches[-1] += group
    agent_batches = [agents[i:i + BATCH_AGENTS] for i in range(0, len(agents), BATCH_AGENTS)] or [[]]
    n = max(len(tool_batches), len(agent_batches))
    return [{"agents": agent_batches[i] if i < len(agent_batches) else [],
             "tools": tool_batches[i] if i < len(tool_batches) else []} for i in range(n)]


def enrich(d: Discovery, base_url: str, model: str, api_key: str = "",
           timeout: float = float(os.environ.get("CRUCIBLE_SYNTHESIS_TIMEOUT", "300")),  # local models on a laptop are slow
           progress: Progress | None = None) -> None:
    """Ask a model for one-sentence purposes and extra questions. Only claims that cite a known fact survive.
    Answers are cached by a hash of the request, so re-scanning an unchanged repository costs nothing."""
    say = progress or (lambda _m: None)
    batches = enrich_batches(d)
    cache = _cache_dir()
    data: dict[str, Any] = {"agents": {}, "tools": {}, "questions": []}
    hits = 0
    for i, batch in enumerate(batches):
        body = ENRICH_PROMPT + json.dumps(batch)[:24000]
        key = hashlib.sha256(f"{model}\n{body}".encode()).hexdigest()
        f = cache / f"{key}.json"
        if f.is_file():
            part, hits = json.loads(f.read_text(encoding="utf-8")), hits + 1
        else:
            if len(batches) > 1:
                say(f"Model request {i + 1} of {len(batches)}")
            r = httpx.post(base_url.rstrip("/") + "/chat/completions", timeout=timeout,
                           headers={"Authorization": f"Bearer {api_key or 'none'}"},
                           json={"model": model, "temperature": 0, "response_format": {"type": "json_object"},
                                 "messages": [{"role": "user", "content": body}]})
            r.raise_for_status()
            text = r.json()["choices"][0]["message"]["content"] or "{}"
            m = re.search(r"\{.*\}", text, re.S)
            part = json.loads(m.group(0) if m else "{}")
            try:
                cache.mkdir(parents=True, exist_ok=True)
                f.write_text(json.dumps(part), encoding="utf-8")
            except OSError:
                pass
        data["agents"].update(part.get("agents") or {})
        data["tools"].update(part.get("tools") or {})
        data["questions"] += part.get("questions") or []
    changed = 0
    for aid, purpose in data["agents"].items():
        ag = d.agent(aid)
        if ag and isinstance(purpose, str) and purpose.strip():
            ag.purpose = _sentence(purpose, 240)
            changed += 1
    for tname, desc in data["tools"].items():
        t = d.tool(tname)
        if t and isinstance(desc, str) and desc.strip() and not t.description:
            t.description = _sentence(desc, 240)
            changed += 1
    for item in data["questions"][:5]:
        ev = [e for e in (item.get("evidence") or []) if e in d.facts]
        text = str(item.get("text") or "").strip()
        about = str(item.get("about") or "")
        if ev and text and re.match(r"^(agent|tool):", about):
            d.questions.append(Question(id=f"q{len(d.questions) + 1}", text=text[:300], about=about, evidence=ev))
            changed += 1
    sent = [{"fact": e["fact"], "file": e["file"], "line": e["line"]}
            for b in batches for x in b["agents"] + b["tools"] for e in x["evidence"]]
    d.synthesis = {"model": model, "base_url": base_url, "used": True, "changes": changed, "requests": len(batches),
                   "cached": hits, "sent": sent, "chars": sum(len(json.dumps(b)) for b in batches)}


def discover(root: Path, *, include: list[str] | None = None, llm_base_url: str | None = None, llm_model: str | None = None,
             llm_api_key: str = "", source: str | None = None, progress: Progress | None = None) -> Discovery:
    say = progress or (lambda _m: None)
    inv, c = collect(root, include, say)
    d = assemble(inv, c, source)
    if llm_base_url and llm_model:
        batches = enrich_batches(d)
        size = sum(len(json.dumps(b)) for b in batches)
        say(f"Asking {llm_model} to describe {len(d.agents)} agents and {len(d.tools)} tools "
            f"({size // 1000 + 1} KB of redacted snippets, {len(batches)} request{'s' if len(batches) > 1 else ''})")
        try:
            enrich(d, llm_base_url, llm_model, llm_api_key, progress=say)
            if d.synthesis.get("cached"):
                say(f"Reused {d.synthesis['cached']} cached model answers (the code hasn't changed)")
        except Exception as e:  # noqa: BLE001 - the deterministic map stands on its own
            d.synthesis = {"model": llm_model, "used": False, "error": f"{type(e).__name__}: {str(e)[:200]}"}
            say(f"Model step skipped: {d.synthesis['error']}")
    else:
        d.synthesis = {"used": False}
    say(f"Mapped {sum(a.include for a in d.agents)} agents to test, {len(d.tools)} tools, {len(d.questions)} questions")
    return d


def dump(d: Discovery) -> dict[str, Any]:
    """JSON-safe dict without private attributes."""
    return json.loads(d.model_dump_json())
