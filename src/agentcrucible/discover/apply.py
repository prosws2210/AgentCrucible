"""Write the approved plan, validate it, smoke-run it, and compare what happened with what discovery predicted."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Callable

import yaml

from ..config import load_config, load_scenarios
from ..runner import Runner, RunOptions
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


async def _connection_check(out: Path, model: str | None) -> list[dict[str, Any]]:
    """The plan's step 6.2: the model server, every MCP server and every agent's start command, before the smoke run."""
    import httpx

    from ..audit import Target
    cfg = load_config(out)
    want = model or cfg.model
    checks: list[dict[str, Any]] = []
    try:
        async with httpx.AsyncClient(timeout=10) as http:
            r = await http.get(cfg.llm.upstream_base_url.rstrip("/") + "/models",
                               headers={"Authorization": f"Bearer {cfg.llm.api_key}"} if cfg.llm.api_key else {})
        names = {m.get("id") for m in r.json().get("data", [])} if r.status_code == 200 else set()
        # a server that answers but doesn't list models (404) may still serve the model; only a missing model fails
        ok = r.status_code != 200 or not names or want in names or f"{want}:latest" in names
        detail = f"{cfg.llm.upstream_base_url} · " + (f"{want} available" if names and ok else
                                                      f"{want} not found ({len(names)} models)" if not ok else "answering")
    except Exception as e:  # noqa: BLE001
        ok, detail = False, f"{cfg.llm.upstream_base_url} unreachable: {type(e).__name__}"
    checks.append({"id": "model", "ok": ok, "detail": detail})
    for name, spec in cfg.mcp_servers.items():
        t = Target(spec.command, spec.url, spec.env, str((out / spec.cwd).resolve()) if spec.cwd else str(out), spec.headers, spec.transport)
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
        checks.append({"id": f"agent:{name}", "ok": ok, "detail": f"`{a.command}`" + ("" if ok else f" · {script} not found or invalid")})
    return checks


def connection_check(out: Path, model: str | None = None) -> list[dict[str, Any]]:
    return asyncio.run(_connection_check(out, model))


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
              on_episode: Callable[[Any], None] | None = None) -> tuple[dict[str, Any], Path]:
    cfg = load_config(out)
    pairs = [(sc, 1) for sc, _ in load_scenarios(cfg)]
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
        if ag.model.value and not ag.model.env and asked and ag.model.value not in asked:
            findings.append({"kind": "different_model", "agent": ag.id,
                             "detail": f"Expected `{ag.model.value}`, the agent asked for `{', '.join(sorted(asked))}`.",
                             "action": "Check the model setting. Tests use the forced test model either way."})
        for t, n in seen.items():
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
    fixed = apply_fixes(d, root)
    if fixed:
        say(f"Applied {len(fixed)} accepted code changes: {', '.join(fixed)}")
    out, written = write_project(d, root, out, model=model, upstream=upstream)
    say(f"Wrote {len(written)} files to {out}")
    info = validate(out)
    say(f"Config valid: {len(info['agents'])} agents, {info['scenarios']} scenarios")
    result: dict[str, Any] = {"out": str(out), "files": written, "validate": info, "code_changes": fixed}
    if smoke and info["scenarios"]:
        conn = connection_check(out, model)
        result["connection"] = conn
        bad = [c for c in conn if not c["ok"]]
        say(f"Connection check: {len(conn) - len(bad)}/{len(conn)} ok" + (" · " + "; ".join(f"{c['id']}: {c['detail']}" for c in bad) if bad else ""))
        if any(c["id"] == "model" for c in bad):
            say("Smoke run skipped: the model server isn't reachable. Start it and approve again.")
            return result
        say("Smoke run: one attempt per scenario")
        run, run_dir = smoke_run(out, model=model, cache=cache, on_episode=on_episode)
        tuned = tune_budgets(d, out, run)
        if tuned:
            say(f"Budgets set from the smoke run for {len(tuned)} scenarios")
        rep = reality(d, run, run_dir)
        (run_dir / "reality.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        (out / ".crucible").mkdir(exist_ok=True)
        (out / ".crucible" / "import-report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        result.update(run_id=run["run_id"], summary=run["summary"], reality=rep)
        say(f"Smoke run: {rep['passed']}/{rep['episodes']} passed, {len(rep['findings'])} findings")
    return result
