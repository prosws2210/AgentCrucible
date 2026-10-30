"""A knowledge graph of a codebase: its files and how they import each other, and every agent, tool, MCP server, prompt,
skill, database, API and vector store found in it, with what uses what.

Built from `discovery.json` plus the repository's imports, so it needs no model. `crucible discover --apply` writes it
into the repository as `agent-tests/knowledge-graph.json` and a self-contained viewer, `agent-tests/knowledge-graph.html`
(open it in a browser, no server or network needed); `crucible graph` rebuilds both; the dashboard shows the same viewer.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

from .schema import Discovery

MAX_FILES = 600  # files beyond the ones agents and tools live in, followed through imports
CODE_SUFFIXES = (".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts", ".go", ".java")
TS_IMPORT = re.compile(r"""(?:import|export)\s[^'"]*?from\s*['"]([^'"]+)['"]|require\(\s*['"]([^'"]+)['"]\s*\)|import\(\s*['"]([^'"]+)['"]\s*\)""")


def _file_of(d: Discovery, fact_ids: list[str]) -> tuple[str | None, int | None]:
    for fid in fact_ids:
        f = d.facts.get(fid)
        if f and f.evidence:
            return f.evidence[0].file, f.evidence[0].line
    return None, None


def _py_modules(root: Path, files: set[str]) -> dict[str, str]:
    """dotted module -> repo-relative file, for every Python file in the repository (and under src/)."""
    out: dict[str, str] = {}
    for rel in files:
        if not rel.endswith(".py"):
            continue
        parts = Path(rel).with_suffix("").parts
        if parts and parts[-1] == "__init__":
            parts = parts[:-1]
        for start in range(len(parts)):  # src/app/x.py is importable as app.x too
            out.setdefault(".".join(parts[start:]), rel)
    return out


def _imports(root: Path, rel: str, modules: dict[str, str], files: set[str]) -> set[str]:
    """Repo files that `rel` imports."""
    path = root / rel
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return set()
    found: set[str] = set()
    if rel.endswith(".py"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return set()
        pkg = list(Path(rel).with_suffix("").parts[:-1])
        for n in ast.walk(tree):
            names: list[str] = []
            if isinstance(n, ast.Import):
                names = [a.name for a in n.names]
            elif isinstance(n, ast.ImportFrom):
                base = n.module or ""
                if n.level:
                    up = pkg[: len(pkg) - (n.level - 1)] if n.level > 1 else pkg
                    base = ".".join([*up, base] if base else up)
                names = [base] + [f"{base}.{a.name}" if base else a.name for a in n.names]
            for name in names:
                while name:
                    if name in modules and modules[name] != rel:
                        found.add(modules[name])
                        break
                    name = name.rpartition(".")[0]
    elif rel.endswith((".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".mts")):
        for m in TS_IMPORT.finditer(text):
            spec = next(g for g in m.groups() if g)
            if not spec.startswith("."):
                continue
            base = (Path(rel).parent / spec).as_posix()
            base = str(Path(base)).replace("\\", "/")
            parts: list[str] = []
            for seg in base.split("/"):
                if seg == "..":
                    parts = parts[:-1]
                elif seg not in (".", ""):
                    parts.append(seg)
            base = "/".join(parts)
            for cand in [base, *(base + s for s in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".mts")),
                         *(base + "/index" + s for s in (".ts", ".tsx", ".js"))]:
                if cand in files:
                    found.add(cand)
                    break
    return found


def build_graph(d: Discovery, root: Path | None = None) -> dict[str, Any]:
    """Nodes and edges for the knowledge graph (JSON-serialisable)."""
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, str]] = []
    seen_edges: set[tuple[str, str, str]] = set()

    def node(nid: str, kind: str, label: str, file: str | None = None, line: int | None = None, **meta: Any) -> str:
        if nid not in nodes:
            nodes[nid] = {"id": nid, "kind": kind, "label": label, "file": file, "line": line,
                          **{k: v for k, v in meta.items() if v not in (None, [], "", {})}}
        return nid

    def edge(a: str, b: str, kind: str) -> None:
        if a in nodes and b in nodes and a != b and (a, b, kind) not in seen_edges:
            seen_edges.add((a, b, kind))
            edges.append({"source": a, "target": b, "kind": kind})

    def file_node(rel: str | None) -> str | None:
        if not rel:
            return None
        return node(f"file:{rel}", "file", Path(rel).name, rel, None, path=rel)

    # the things discovery found, each defined in a file; an unticked "agent" in a test or a script is a fixture, not
    # part of the system, so it stays in the review (where it can be ticked) but not on the map
    from .synthesize import SCRIPT_FILE, TEST_FILE
    for ag in d.agents:
        f, ln = _file_of(d, ag.evidence)
        if not ag.include and f and (TEST_FILE.search(f) or SCRIPT_FILE.search(f)):
            continue
        node(f"agent:{ag.id}", "agent", ag.name, f, ln, framework=ag.framework, purpose=ag.purpose,
             included=ag.include, model=ag.model.value or ag.model.env, service=ag.service, memory=ag.memory)
        edge(file_node(f) or "", f"agent:{ag.id}", "defines")
    for t in d.tools:
        f, ln = _file_of(d, t.evidence)
        node(f"tool:{t.name}", "tool", t.name, f, ln, effects=t.effects, description=t.description,
             tool_kind=t.kind, server=t.server)
        if t.kind != "mcp" or not t.server:
            edge(file_node(f) or "", f"tool:{t.name}", "defines")
    for s in d.mcp_servers:
        f, ln = _file_of(d, s.evidence)
        node(f"mcp:{s.name}", "mcp_server", s.name, f, ln, command=s.command, url=s.url, defined_here=s.defined_here)
        edge(file_node(f) or "", f"mcp:{s.name}", "defines" if s.defined_here else "configures")
    for s in d.datastores:
        f, ln = _file_of(d, s.evidence)
        node(f"datastore:{s.id}", "datastore", s.id, f, ln, store_kind=s.kind, tables=list(s.tables)[:30],
             url_env=s.url_env)
    for a in d.external_apis:
        f, ln = _file_of(d, a.evidence)
        node(f"api:{a.id}", "api", a.id, f, ln, base_url=a.base_url, base_url_env=a.base_url_env, api_kind=a.kind,
             paths=a.paths[:20])
    for v in d.vector_stores:
        f, ln = _file_of(d, v.evidence)
        node(f"vector:{v.id}", "vector_store", v.id, f, ln, store_kind=v.kind)
    for sk in d.skills:
        node(f"skill:{sk.name}", "skill", sk.name, sk.file, None, description=sk.description)
        edge(file_node(sk.file) or "", f"skill:{sk.name}", "defines")

    # how they connect
    for ag in d.agents:
        a = f"agent:{ag.id}"
        for t in ag.tools:
            edge(a, f"tool:{t}", "uses")
        for sub in ag.subagents:
            edge(a, f"agent:{sub}", "hands off to")
        for s in ag.mcp_servers:
            edge(a, f"mcp:{s}", "connects to")
        for s in ag.datastores:
            edge(a, f"datastore:{s}", "reads/writes")
        for s in ag.external_apis:
            edge(a, f"api:{s}", "calls")
        if ag.system_prompt.file:
            pid = node(f"prompt:{ag.system_prompt.file}", "prompt", Path(ag.system_prompt.file).name,
                       ag.system_prompt.file, None)
            edge(a, pid, "loads prompt")
            edge(file_node(ag.system_prompt.file) or "", pid, "defines")
        ep = ag.entrypoint
        if ep.kind in ("http", "cli") and (ep.route or ep.command):
            label = ep.route or ep.command or ""
            eid = node(f"entry:{label}", "entrypoint", label, *_file_of(d, ep.evidence), entry_kind=ep.kind)
            edge(eid, a, "runs")
    for t in d.tools:
        tid = f"tool:{t.name}"
        if t.server:
            edge(f"mcp:{t.server}", tid, "provides")
        for touch in t.touches:
            kind, _, ref = touch.partition(":")
            target = {"datastore": "datastore", "api": "api", "vector": "vector"}.get(kind)
            if target:
                edge(tid, f"{target}:{ref}", "touches")
    for s in d.mcp_servers:
        for t in s.tools:
            edge(f"mcp:{s.name}", f"tool:{t}", "provides")

    # files that hold findings, and the files they import (so the graph shows how the code is wired)
    root = root or Path(d.repo.root)
    all_files: set[str] = set()
    if root.is_dir():
        from .scan import scan
        all_files = {f.rel for f in scan(root).files if f.rel.endswith(CODE_SUFFIXES)}
    modules = _py_modules(root, all_files)
    frontier = [n["file"] for n in nodes.values() if n["kind"] == "file" and n["file"] in all_files]
    done: set[str] = set()
    while frontier and len(done) < MAX_FILES:
        rel = frontier.pop()
        if rel in done:
            continue
        done.add(rel)
        for dep in sorted(_imports(root, rel, modules, all_files)):
            file_node(dep)
            edge(f"file:{rel}", f"file:{dep}", "imports")
            if dep not in done:
                frontier.append(dep)
    # who imports the files agents live in (entry points, servers, CLIs)
    agent_files = {n["file"] for n in nodes.values() if n["kind"] in ("agent", "mcp_server") and n["file"]}
    for rel in sorted(all_files - done)[: MAX_FILES]:
        deps = _imports(root, rel, modules, all_files) & agent_files
        for dep in deps:
            file_node(rel)
            edge(f"file:{rel}", f"file:{dep}", "imports")

    counts: dict[str, int] = {}
    for n in nodes.values():
        counts[n["kind"]] = counts.get(n["kind"], 0) + 1
    return {"version": 1, "repo": {"name": d.repo.name, "root": d.repo.root, "commit": d.repo.commit},
            "generated_by": d.generator, "counts": counts, "nodes": list(nodes.values()), "edges": edges}


def viewer_html(graph: dict[str, Any]) -> str:
    """The self-contained viewer with the graph embedded (works from a file:// URL)."""
    template = (Path(__file__).parent / "graph_viewer.html").read_text(encoding="utf-8")
    data = json.dumps(graph).replace("</", "<\\/")
    return template.replace("/*__GRAPH__*/null", data, 1)


def write_graph(d: Discovery, root: Path, out: Path) -> list[str]:
    """Write knowledge-graph.json and knowledge-graph.html into `out` (agent-tests/). Returns the file names."""
    g = build_graph(d, root)
    out.mkdir(parents=True, exist_ok=True)
    (out / "knowledge-graph.json").write_text(json.dumps(g, indent=1), encoding="utf-8")
    (out / "knowledge-graph.html").write_text(viewer_html(g), encoding="utf-8")
    return ["knowledge-graph.json", "knowledge-graph.html"]
