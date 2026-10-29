"""Write the approved plan, validate it, smoke-run it, and compare what happened with what discovery predicted."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Callable

from ..config import load_config, load_scenarios
from ..runner import Runner, RunOptions
from ..trajectory import load_events
from .plan import OUT_DIR, build_plan, project_files
from .schema import Discovery

Progress = Callable[[str], None]


def write_project(d: Discovery, root: Path, out: Path | None = None, model: str = "qwen2.5:7b",
                  upstream: str = "http://localhost:11434/v1") -> tuple[Path, list[str]]:
    out = out or root / OUT_DIR
    if not d.plans:
        build_plan(d, root)
    files = project_files(d, root, model=model, upstream=upstream)
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


def validate(out: Path) -> dict[str, Any]:
    cfg = load_config(out)
    pairs = load_scenarios(cfg)
    return {"agents": sorted(cfg.agents), "scenarios": len(pairs), "suites": sorted(cfg.suites)}


def smoke_run(out: Path, model: str | None = None, cache: str | None = None, parallel: int = 2,
              on_episode: Callable[[Any], None] | None = None) -> tuple[dict[str, Any], Path]:
    cfg = load_config(out)
    pairs = [(sc, 1) for sc, _ in load_scenarios(cfg)]
    runner = Runner(cfg, RunOptions(label="import-smoke", parallel=parallel, model=model, cache=cache), on_episode)
    run = asyncio.run(runner.run(pairs))
    return run, runner.run_dir


def reality(d: Discovery, run: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    """Compare the smoke run's trajectories with the agent map (plan section 9)."""
    observed_tools: dict[str, dict[str, int]] = {}  # agent -> tool -> calls
    models: dict[str, set[str]] = {}
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
                for r in e.get("tool_requests") or []:
                    if r.get("name") and r["name"] not in executed:
                        tools[r["name"]] = tools.get(r["name"], 0) + 1
            elif e["type"] == "tool_result" and e.get("is_error"):
                failures.append({"kind": "tool_error", "agent": agent, "tool": e.get("tool"), "detail": str(e.get("content", ""))[:300],
                                 "scenario": ep["scenario_id"], "action": "Check the fixture data or the tool's inputs."})
        if ep.get("error"):
            failures.append({"kind": "agent_error", "agent": agent, "detail": ep["error"][:400], "scenario": ep["scenario_id"],
                             "action": "See the episode log; usually an import error or a missing setting in the adapter."})
    findings: list[dict[str, Any]] = []
    for ag in d.agents:
        if not ag.include:
            continue
        seen = observed_tools.get(ag.id, {})
        n_eps = sum(1 for ep in run["episodes"] if scen_agent.get(ep["scenario_id"]) == ag.id)
        for t in ag.tools:
            if t not in seen and n_eps:
                findings.append({"kind": "tool_never_called", "agent": ag.id, "tool": t,
                                 "detail": f"`{t}` was never used in {n_eps} episodes.",
                                 "action": "Add or fix a scenario that needs it, or mark it unused."})
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
        "findings": findings,
        "scenarios": outcomes,
        "run_id": run["run_id"],
    }


def apply(d: Discovery, root: Path, out: Path | None = None, *, model: str = "qwen2.5:7b",
          upstream: str = "http://localhost:11434/v1", smoke: bool = True, cache: str | None = None,
          progress: Progress | None = None, on_episode: Callable[[Any], None] | None = None) -> dict[str, Any]:
    say = progress or (lambda _m: None)
    out, written = write_project(d, root, out, model=model, upstream=upstream)
    say(f"Wrote {len(written)} files to {out}")
    info = validate(out)
    say(f"Config valid: {len(info['agents'])} agents, {info['scenarios']} scenarios")
    result: dict[str, Any] = {"out": str(out), "files": written, "validate": info}
    if smoke and info["scenarios"]:
        say("Smoke run: one attempt per scenario")
        run, run_dir = smoke_run(out, model=model, cache=cache, on_episode=on_episode)
        rep = reality(d, run, run_dir)
        (run_dir / "reality.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        (out / ".crucible").mkdir(exist_ok=True)
        (out / ".crucible" / "import-report.json").write_text(json.dumps(rep, indent=2), encoding="utf-8")
        result.update(run_id=run["run_id"], summary=run["summary"], reality=rep)
        say(f"Smoke run: {rep['passed']}/{rep['episodes']} passed, {len(rep['findings'])} findings")
    return result
