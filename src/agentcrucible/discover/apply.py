"""Write the approved plan, validate it, smoke-run it, and compare what happened with what discovery predicted."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from ..config import load_config, load_scenarios
from ..pyenv import project_python
from ..runner import Runner, RunOptions, scaffold_pending
from ..trajectory import load_events
from .plan import OUT_DIR, apply_fixes, build_plan, project_files
from .schema import Discovery

Progress = Callable[[str], None]


def write_project(d: Discovery, root: Path, out: Path | None = None, model: str = "qwen2.5:7b",
                  upstream: str = "http://localhost:11434/v1") -> tuple[Path, list[str]]:
    out = out or root / OUT_DIR
    if not d.plans:
        build_plan(d, root)
    files = project_files(d, root, model=model, upstream=upstream)
    _remove_stale(out, files)
    written = []
    for rel, content in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        written.append(rel)
    d.approved = True
    (out / "discovery.json").write_text(d.model_dump_json(indent=2), encoding="utf-8")
    written.append("discovery.json")
    from .graph import write_graph
    written += write_graph(d, root, out)  # knowledge-graph.json + a viewer you can open from the repo
    gi = out / ".gitignore"
    if not gi.exists():
        gi.write_text(".crucible/\n", encoding="utf-8")
    return out, sorted(written)


def _remove_stale(out: Path, files: dict[str, str]) -> list[str]:
    """Delete scenarios and adapters an earlier apply wrote that the new plan no longer has (a removed agent, a draft
    switched off). Only files still exactly as generated go; anything the user edited stays."""
    f = out / "discovery.json"
    if not f.is_file():
        return []
    try:
        old = Discovery.model_validate_json(f.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return []
    before = {f"scenarios/{s.agent}/{s.id}.yaml": s.yaml for s in old.scenarios if s.include}
    before.update({p.adapter_file.removeprefix(OUT_DIR + "/"): p.adapter_code for p in old.plans
                   if p.adapter_file and p.adapter_code})
    gone = []
    for rel, text in before.items():
        p = out / rel
        if rel not in files and p.is_file() and p.read_text(encoding="utf-8") == text:
            p.unlink()
            gone.append(rel)
            if p.parent.name != "adapters" and p.parent.is_dir() and not any(p.parent.iterdir()):
                p.parent.rmdir()
    return gone


def validate(out: Path) -> dict[str, Any]:
    cfg = load_config(out)
    pairs = load_scenarios(cfg)
    return {"agents": sorted(cfg.agents), "scenarios": len(pairs), "suites": sorted(cfg.suites)}


def _requirements_hint(root: Path, import_root: str) -> str:
    """The install command for the code's dependencies, from the nearest requirements file."""
    base = root / import_root if import_root else root
    for name in ("requirements.txt", "pyproject.toml"):
        if (base / name).is_file():
            rel = (base / name).relative_to(root).as_posix()
            return f"pip install -r {rel}" if name.endswith(".txt") else f"pip install -e {(base.relative_to(root).as_posix() or '.')}"
    return "pip install the project's dependencies"


# what a setting mapped to a fixture holds during the import check (nothing listens there; it only has to parse)
PLACEHOLDER = {"db": "postgresql://agentcrucible:agentcrucible@127.0.0.1:9/agentcrucible", "dbpath": "/nonexistent/agentcrucible.db",
               "http": "http://127.0.0.1:9", "openai": "http://127.0.0.1:9/v1", "anthropic": "http://127.0.0.1:9"}


async def _import_check(cfg: Any, out: Path, d: Discovery, root: Path) -> dict[str, dict[str, Any]]:
    """Import each Python agent's module the way its adapter will (same interpreter, folder, path and environment),
    so a missing dependency shows up here in seconds, not as every scenario failing in the smoke run."""
    from ..gateway import child_env, split_command
    project = project_python(cfg)[0]
    jobs: dict[tuple[str, str, str], list[str]] = {}  # (python, module, import root) -> agent names
    for name, a in cfg.agents.items():
        ag = d.agent(name)
        ep = ag.entrypoint if ag else None
        if not ag or ag.language != "python" or not ep or ep.kind != "code" or not ep.module or not a.command:
            continue
        python = split_command(a.command, project)[0]
        fact = d.facts.get(ag.evidence[0]) if ag.evidence else None
        ir = (fact.attrs.get("import_root") if fact else None) or ""
        jobs.setdefault((python, ep.module, ir), []).append(name)
    sem = asyncio.Semaphore(4)

    async def one(python: str, module: str, ir: str, names: list[str]) -> dict[str, Any]:
        a = cfg.agents[names[0]]
        cwd = (out / a.cwd).resolve() if a.cwd else out
        # the environment a run gives the agent (gateway keys included: clients are often built at import time); settings
        # its adapter points at fixtures get a placeholder of the same kind, since code often checks them on import
        plan = next((pl for pl in d.plans if pl.agent == names[0]), None)
        mapped = {k: PLACEHOLDER.get(t.partition(":")[0], "") for k, t in (plan.env_map if plan else {}).items()}
        env = {**child_env(a.env, mapped, inherit=a.inherit_env), "OPENAI_BASE_URL": "http://127.0.0.1:9/v1", "OPENAI_API_KEY": "agentcrucible",
               "OPENAI_API_BASE": "http://127.0.0.1:9/v1", "ANTHROPIC_BASE_URL": "http://127.0.0.1:9",
               "ANTHROPIC_API_KEY": "agentcrucible", "CRUCIBLE_MODEL": cfg.model, "PYTHONIOENCODING": "utf-8",
               "PYTHONDONTWRITEBYTECODE": "1"}  # a check leaves nothing behind in the repository
        base = root / ir if ir else root
        paths = [str(base)] + ([str(base / "src")] if (base / "src").is_dir() else [])
        code = f"import sys, importlib; sys.path[:0] = {paths!r}; importlib.import_module({module!r})"
        async with sem:
            try:
                proc = await asyncio.create_subprocess_exec(python, "-c", code, cwd=str(cwd), env=env, stdout=asyncio.subprocess.DEVNULL,
                                                            stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
                _, err = await asyncio.wait_for(proc.communicate(), 120)
            except asyncio.TimeoutError:
                proc.kill()
                return {"ok": True, "detail": f"importing {module} took over 2 minutes; left to the smoke run"}
            except OSError as e:
                return {"ok": False, "detail": f"`{python}` couldn't start: {e.strerror or e}"}
        if proc.returncode == 0:
            return {"ok": True, "detail": f"imports {module}"}
        lines = [ln.strip() for ln in err.decode("utf-8", "replace").splitlines() if ln.strip()]
        cause = next((ln for ln in reversed(lines) if re.match(r"[\w.]*(Error|Exception)\b", ln)), lines[-1] if lines else "failed")
        missing = re.search(r"No module named '([^']+)'", cause)
        hint = (f"; install the code's dependencies where AgentCrucible runs it ({_requirements_hint(root, ir)}), "
                "or run the tests from your project's own environment (crucible run -c agent-tests)") if missing else ""
        return {"ok": False, "detail": f"can't import {module}: {cause[:200]}{hint}",
                "missing": missing.group(1).split(".")[0] if missing else None}

    results = await asyncio.gather(*(one(*k, names) for k, names in jobs.items()))
    return {name: r for k, r in zip(jobs, results, strict=True) for name in jobs[k]}


async def _connection_check(out: Path, model: str | None, d: Discovery | None = None,
                            root: Path | None = None) -> list[dict[str, Any]]:
    """The plan's step 6.2: the model server, every MCP server and every agent's start command, before the smoke run."""

    from ..audit import Target
    cfg = load_config(out)
    want = model or cfg.model
    checks: list[dict[str, Any]] = []
    from ..gateway import list_models
    answered, listed, error = await list_models(cfg.llm.upstream_base_url, cfg.llm.api_key)
    names = set(listed)
    unreachable = not answered and ("ConnectError" in error or "Timeout" in error)
    # a server that answers but doesn't list models may still serve the model; only a missing model fails
    ok = not unreachable and (not names or want in names or f"{want}:latest" in names)
    detail = f"{cfg.llm.upstream_base_url} · " + (f"unreachable: {error}" if unreachable else f"{want} available" if names and ok
                                                  else f"{want} not found ({len(names)} models)" if not ok else "answering")
    checks.append({"id": "model", "ok": ok, "detail": detail})
    for name, spec in cfg.mcp_servers.items():
        t = Target(spec.command, spec.url, spec.env, str((out / spec.cwd).resolve()) if spec.cwd else str(out), spec.headers,
                   spec.transport, project_python(cfg)[0])
        try:
            await asyncio.wait_for(t.connect(), 30)
            tools = (await t.session.list_tools()).tools  # type: ignore[union-attr]
            checks.append({"id": f"mcp:{name}", "ok": True, "detail": f"{len(tools)} tools: " + ", ".join(x.name for x in tools[:8])})
        except Exception as e:  # noqa: BLE001
            checks.append({"id": f"mcp:{name}", "ok": False, "detail": f"failed to start: {type(e).__name__}: {str(e)[:160]}"})
        finally:
            await t.close()
    for name, a in cfg.agents.items():
        cwd = (out / a.cwd).resolve() if a.cwd else out
        script = next((p for p in (a.command or "").split()[1:] if p.endswith((".py", ".js", ".ts", ".mjs"))), None)
        ok = script is None or (cwd / script).exists()
        if ok and script and script.endswith(".py"):
            try:
                compile((cwd / script).read_text(encoding="utf-8"), script, "exec")
            except SyntaxError as e:
                ok, script = False, f"{script} has a syntax error on line {e.lineno}"
        detail = f"`{a.command}`" + ("" if ok else f" · {script} not found or invalid")
        if ok and scaffold_pending(cfg, name):
            ok, detail = False, f"{detail} · its adapter is a scaffold to finish: fill in `turn` in {script}"
        checks.append({"id": f"agent:{name}", "ok": ok, "detail": detail})
    if d is not None and root is not None:
        imports = await _import_check(cfg, out, d, root)
        for c in checks:
            r = imports.get(c["id"].removeprefix("agent:")) if c["id"].startswith("agent:") else None
            if r and c["ok"]:
                c.update(ok=r["ok"], detail=f"{c['detail']} · {r['detail']}", **({"missing": r["missing"]} if r.get("missing") else {}))
    return checks


def connection_check(out: Path, model: str | None = None, d: Discovery | None = None,
                     root: Path | None = None) -> list[dict[str, Any]]:
    return asyncio.run(_connection_check(out, model, d, root))


def tune_budgets(d: Discovery, out: Path, run: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Set each scenario's budget from what the smoke run used (the plan: budgets come from the smoke run).
    Generous (2x + headroom) and non-blocking, so a slightly longer path is reported but doesn't fail the run."""
    used: dict[str, dict[str, int]] = {}
    for ep in run["episodes"]:
        t = ep.get("totals") or {}
        if ep.get("error") or not t.get("llm_calls"):
            continue
        used[ep["scenario_id"]] = {"max_llm_calls": max(5, 2 * t["llm_calls"] + 2),
                                   "max_tokens": max(4000, 3 * (t.get("tokens_in", 0) + t.get("tokens_out", 0)))}
    for sc in d.scenarios:
        b = used.get(sc.id)
        if not b:
            continue
        data = yaml.safe_load(sc.yaml)
        checks = [c for c in data.get("checks", []) if not (isinstance(c, dict) and set(c) & {"budget.max_llm_calls", "budget.max_tokens"})]
        checks += [{"budget.max_llm_calls": {"max": b["max_llm_calls"], "hard": False}},
                   {"budget.max_tokens": {"max": b["max_tokens"], "hard": False}}]
        data["checks"] = checks
        sc.yaml = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=110)
        f = out / "scenarios" / sc.agent / f"{sc.id}.yaml"
        if f.exists():
            f.write_text(sc.yaml, encoding="utf-8")
    if used:
        (out / "discovery.json").write_text(d.model_dump_json(indent=2), encoding="utf-8")
    return used


def smoke_run(out: Path, model: str | None = None, cache: str | None = None, parallel: int = 2,
              on_episode: Callable[[Any], None] | None = None, skip_agents: set[str] | None = None) -> tuple[dict[str, Any], Path]:
    cfg = load_config(out)
    skip = skip_agents or set()
    pairs = [(sc, 1) for suite, spec in cfg.suites.items() if spec.agent not in skip for sc, _ in load_scenarios(cfg, suite)]
    runner = Runner(cfg, RunOptions(label="import-smoke", parallel=parallel, model=model, cache=cache), on_episode)
    run = asyncio.run(runner.run(pairs))
    return run, runner.run_dir


def _log_cause(run_dir: Path, error: str) -> str | None:
    """The line that explains a crash ("ModuleNotFoundError: No module named 'anthropic'"), from the agent's log."""
    m = re.search(r"logs/(\S+?\.log)", error)
    if not m:
        return None
    try:
        lines = (run_dir / "logs" / m.group(1)).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    hits = [ln.strip() for ln in lines if re.match(r"\s*\w*(Error|Exception)\b.*:", ln) or re.match(r"\s*Error:", ln)]
    return hits[-1][:300] if hits else None


def reality(d: Discovery, run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Compare the smoke run's trajectories with the agent map (plan section 9)."""
    observed_tools: dict[str, dict[str, int]] = {}  # agent -> tool -> calls
    models: dict[str, set[str]] = {}
    requested: dict[str, set[str]] = {}  # the model the agent's code asked for, before the test model replaced it
    failures: list[dict[str, Any]] = []
    scen_agent = {}
    for sc in run["scenarios"]:
        draft = next((s for s in d.scenarios if s.id == sc["id"]), None)
        scen_agent[sc["id"]] = draft.agent if draft else None
    for ep in run["episodes"]:
        agent = scen_agent.get(ep["scenario_id"])
        if agent is None:
            continue
        events = load_events(run_dir / ep["trajectory"])
        tools = observed_tools.setdefault(agent, {})
        executed = {e["tool"] for e in events if e["type"] == "tool_call"}
        for e in events:
            if e["type"] == "tool_call":
                tools[e["tool"]] = tools.get(e["tool"], 0) + 1
            elif e["type"] == "llm_call":
                if e.get("model"):
                    models.setdefault(agent, set()).add(e["model"])
                if e.get("requested_model"):
                    requested.setdefault(agent, set()).add(e["requested_model"])
                for r in e.get("tool_requests") or []:
                    if r.get("name") and r["name"] not in executed:
                        tools[r["name"]] = tools.get(r["name"], 0) + 1
            elif e["type"] == "tool_result" and e.get("is_error"):
                failures.append({"kind": "tool_error", "agent": agent, "tool": e.get("tool"), "detail": str(e.get("content", ""))[:300],
                                 "scenario": ep["scenario_id"], "action": "Check the fixture data or the tool's inputs."})
        if ep.get("error"):
            cause = _log_cause(run_dir, ep["error"])
            failures.append({"kind": "agent_error", "agent": agent, "scenario": ep["scenario_id"],
                             "detail": (f"{cause} ({ep['scenario_id']})" if cause else ep["error"][:400]),
                             "action": "Install what the agent imports in the environment AgentCrucible runs it in, or set the "
                                       "missing setting; the full log is in " + (re.search(r"logs/\S+", ep["error"]) or ["the run folder"])[0]})
    findings: list[dict[str, Any]] = []
    for ag in d.agents:
        if not ag.include:
            continue
        seen = observed_tools.get(ag.id, {})
        n_eps = sum(1 for ep in run["episodes"] if scen_agent.get(ep["scenario_id"]) == ag.id and not ep.get("error"))
        for t in ag.tools:
            if t not in seen and n_eps:
                findings.append({"kind": "tool_never_called", "agent": ag.id, "tool": t,
                                 "detail": f"`{t}` was never used in {n_eps} episodes.",
                                 "action": "Add or fix a scenario that needs it, or mark it unused."})
        asked = requested.get(ag.id, set())
        bare = lambda m: re.sub(r"^[\w-]+[:/]", "", m or "")  # noqa: E731 - "openai:gpt-5" asks for "gpt-5"
        if ag.model.value and not ag.model.env and asked and bare(ag.model.value) not in {bare(x) for x in asked}:
            findings.append({"kind": "different_model", "agent": ag.id,
                             "detail": f"Expected `{ag.model.value}`, the agent asked for `{', '.join(sorted(asked))}`.",
                             "action": "Check the model setting. Tests use the forced test model either way."})
        handoffs = {"transfer_to_" + re.sub(r"[^a-z0-9]+", "_", (d.agent(s).name if d.agent(s) else s).lower()).strip("_")
                    for s in ag.subagents}
        for t, n in seen.items():
            if t.startswith("transfer_to_") and (t in handoffs or ag.subagents) or t.startswith("final_result"):
                continue  # tools a framework makes itself: a handoff, PydanticAI's structured output
            if t not in ag.tools and not any(t in (d.agent(s).tools if d.agent(s) else []) for s in ag.subagents):
                findings.append({"kind": "unexpected_tool", "agent": ag.id, "tool": t,
                                 "detail": f"`{t}` was called {n}x but isn't in the map.", "action": "Add it to the agent's tools."})
    findings += failures
    ok = not failures and all(ep.get("error") is None for ep in run["episodes"])
    reasons = {s.id: s.reason for s in d.scenarios}
    outcomes = [{"scenario": ep["scenario_id"], "agent": scen_agent.get(ep["scenario_id"]), "passed": ep["passed"],
                 "why": reasons.get(ep["scenario_id"], ""), "error": ep.get("error"),
                 "failed": [{"check": c["label"], "detail": str(c.get("detail", ""))[:300]}
                            for c in ep.get("checks", []) if c["hard"] and not c["passed"]]}
                for ep in sorted(run["episodes"], key=lambda e: (e["passed"], e["scenario_id"]))]
    return {
        "ok": ok,
        "episodes": len(run["episodes"]),
        "passed": sum(1 for ep in run["episodes"] if ep["passed"]),
        "errors": sum(1 for ep in run["episodes"] if ep.get("error")),
        "observed_tools": {k: dict(sorted(v.items())) for k, v in observed_tools.items()},
        "models": {k: sorted(v) for k, v in models.items()},
        "requested_models": {k: sorted(v) for k, v in requested.items()},
        "findings": findings,
        "scenarios": outcomes,
        "run_id": run["run_id"],
    }


def apply(d: Discovery, root: Path, out: Path | None = None, *, model: str = "qwen2.5:7b",
          upstream: str = "http://localhost:11434/v1", smoke: bool = True, cache: str | None = None,
          progress: Progress | None = None, on_episode: Callable[[Any], None] | None = None) -> dict[str, Any]:
    say = progress or (lambda _m: None)
    if not any(a.include for a in d.agents):
        raise ValueError("No agent is ticked, so there's nothing to test: include at least one agent"
                         + (" (the ones found are left out, e.g. defined in tests)" if d.agents else ""))
    fixed = apply_fixes(d, root)
    if fixed:
        say(f"Applied {len(fixed)} accepted code changes: {', '.join(fixed)}")
    out, written = write_project(d, root, out, model=model, upstream=upstream)
    say(f"Wrote {len(written)} files to {out}")
    info = validate(out)
    say(f"Config valid: {len(info['agents'])} agents, {info['scenarios']} scenarios")
    result: dict[str, Any] = {"out": str(out), "files": written, "validate": info, "code_changes": fixed}
    if smoke and info["scenarios"]:
        result.update(smoke_and_report(d, root, out, model=model, cache=cache, progress=say, on_episode=on_episode))
    return result


def smoke_and_report(d: Discovery, root: Path, out: Path, *, model: str | None = None, cache: str | None = None,
                     progress: Progress | None = None, on_episode: Callable[[Any], None] | None = None) -> dict[str, Any]:
    """The connection check, then one attempt per scenario, then the discovery vs reality report. Run at approval,
    and again from the results page once what the check found is fixed."""
    say = progress or (lambda _m: None)
    result: dict[str, Any] = {}
    say("Connection check: the model server, every MCP server, and importing each agent's code")
    conn = connection_check(out, model, d, root)
    result["connection"] = conn
    bad = [c for c in conn if not c["ok"]]
    say(f"Connection check: {len(conn) - len(bad)}/{len(conn)} ok" + (" · " + "; ".join(f"{c['id']}: {c['detail']}" for c in bad[:3]) if bad else ""))
    if any(c["id"] == "model" for c in bad):
        result["smoke_skipped"] = "The model server isn't reachable, so the smoke run was skipped. Start it and run the check again."
        say(result["smoke_skipped"])
        return result
    cant_start = {c["id"].removeprefix("agent:") for c in bad if c["id"].startswith("agent:")}
    agents = set(load_config(out).agents)
    if agents and cant_start >= agents:
        missing = sorted({c["missing"] for c in bad if c.get("missing")})
        result["smoke_skipped"] = ("None of the agents can run yet, so the smoke run was skipped"
                                   + (f" (missing: {', '.join(missing[:6])})" if missing else "")
                                   + ". The tests are written; fix what the connection check shows and run them.")
        say(result["smoke_skipped"])
        return result
    if cant_start:
        say(f"Skipping {len(cant_start)} agents that can't run yet: {', '.join(sorted(cant_start))}")
    n = sum(1 for s in d.scenarios if s.include and s.agent not in cant_start)
    say(f"Smoke run: one attempt per scenario ({n} tests)")  # the dashboard reads the count from this line
    run, run_dir = smoke_run(out, model=model, cache=cache, on_episode=on_episode, skip_agents=cant_start)
    tuned = tune_budgets(d, out, run)
    if tuned:
        say(f"Budgets set from the smoke run for {len(tuned)} scenarios")
    rep = reality(d, run, run_dir)
    (run_dir / "reality.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    (out / ".crucible").mkdir(exist_ok=True)
    (out / ".crucible" / "import-report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
    result.update(run_id=run["run_id"], summary=run["summary"], reality=rep, smoke_skipped=None)
    say(f"Smoke run: {rep['passed']}/{rep['episodes']} passed, {len(rep['findings'])} findings")
    return result
