"""Add one agent by hand: the dashboard's "Add an agent" form.

It goes through the same planner as `crucible discover`, so a hand-added agent gets the same adapters as a found one.
In a test project written by `discover` the agent is added to `discovery.json` (re-imports keep it) and the project
is regenerated; in a hand-written `crucible.yaml` the agent, its suite and its first scenario are added to the file.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from .config import load_config, load_scenarios
from .discover.apply import write_project
from .discover.plan import OUT_DIR, _dump, _python, build_plan, plan_agent
from .discover.schema import Agent, Discovery, DraftScenario, Entrypoint, RepoInfo

Kind = Literal["python", "typescript", "java", "go", "http", "command"]
FRAMEWORKS = ("generic", "langgraph", "openai-agents", "pydantic-ai", "crewai", "llamaindex", "google-adk")


class NewAgent(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: Kind
    purpose: str = ""
    # python / typescript / java / go: what to call
    module: str | None = None  # app.agents.support | src/agent | com.acme.SupportAgent | internal/agent
    object: str | None = None  # run, graph, build_agent
    framework: str = "generic"
    factory: bool = False  # `object` is a function that builds the agent
    # http: a web service that takes a message and answers
    app_url: str | None = None  # http://localhost:8000
    route: str = "POST /chat"
    # command: a program that already speaks AgentCrucible's stdio protocol
    command: str | None = None
    # the first test
    task: str = Field(min_length=1, max_length=2000)
    must_call: str = ""
    must_not_call: str = ""
    reply_mentions: str = ""

    @model_validator(mode="after")
    def _check(self) -> "NewAgent":
        if self.kind in ("python", "typescript", "java", "go"):
            if not (self.module and re.fullmatch(r"[\w.\-/@]+", self.module)):
                raise ValueError({"python": "give the module the agent is in, e.g. app.agents.support",
                                  "typescript": "give the file it's exported from, e.g. src/agent",
                                  "java": "give the class, e.g. com.acme.SupportAgent",
                                  "go": "give the package folder, e.g. internal/agent"}[self.kind])
            if not (self.object and re.fullmatch(r"[A-Za-z_]\w*", self.object)):
                raise ValueError("give the name of the function or object to call, e.g. run or graph")
            if self.framework not in FRAMEWORKS:
                raise ValueError(f"framework must be one of {', '.join(FRAMEWORKS)}")
        if self.kind == "http":
            if not (self.app_url and re.fullmatch(r"https?://[^\s]+", self.app_url)):
                raise ValueError("give the address the service runs at, e.g. http://localhost:8000")
            if not re.fullmatch(r"(POST|PUT|GET) /\S*", self.route.strip()):
                raise ValueError("the endpoint looks like `POST /chat`")
        if self.kind == "command" and not (self.command or "").strip():
            raise ValueError("give the command that starts the agent")
        for v in (self.must_call, self.must_not_call):
            if v and not re.fullmatch(r"[\w.\-]+", v.strip()):
                raise ValueError(f"{v!r} isn't a tool name")
        return self


def _agent_id(name: str, taken: set[str]) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "agent"
    aid, n = base, 2
    while aid in taken:
        aid, n = f"{base}-{n}", n + 1
    return aid


def make_agent(spec: NewAgent, taken: set[str]) -> Agent:
    aid = _agent_id(spec.name, taken)
    if spec.kind in ("python", "typescript", "java", "go"):
        ep = Entrypoint(kind="code", module=spec.module, object=spec.object, factory=spec.factory)
    elif spec.kind == "http":
        ep = Entrypoint(kind="http", route=spec.route.strip())
    else:
        ep = Entrypoint(kind="cli", command=spec.command.strip())  # type: ignore[union-attr]
    return Agent(id=aid, name=spec.name.strip(), purpose=spec.purpose.strip(),
                 framework=spec.framework if spec.kind == "python" else "generic",
                 language={"typescript": "typescript", "java": "java", "go": "go"}.get(spec.kind, "python"),
                 entrypoint=ep, confidence="high",
                 added_by_hand=True, app_url=spec.app_url.rstrip("/") if spec.kind == "http" and spec.app_url else None)


def first_scenario(aid: str, spec: NewAgent) -> DraftScenario:
    checks: list[dict] = []
    if spec.must_call.strip():
        checks.append({"trajectory.tool_called": spec.must_call.strip()})
    if spec.must_not_call.strip():
        checks.append({"trajectory.tool_not_called": spec.must_not_call.strip()})
    if spec.reply_mentions.strip():
        checks.append({"output.contains": spec.reply_mentions.strip()})
    checks.append({"judge.rubric": {"criteria": "Handles the request correctly and helpfully.", "min": 3,
                                    "hard": not checks}})
    sid = f"{aid}-first-test"
    sc = {"id": sid, "description": f"First test for {spec.name.strip()}, written by hand", "task": spec.task.strip(),
          "checks": checks}
    return DraftScenario(id=sid, agent=aid, reason="Written by hand when the agent was added", yaml=_dump(sc),
                         edited=True)


def check_code(codebase: Path, spec: NewAgent) -> None:
    """Catch a mistyped module before writing an adapter that can't import it."""
    if spec.kind == "python":
        rel = spec.module.replace(".", "/")  # type: ignore[union-attr]
        cands = [codebase / base / rel for base in (".", "src")]
        if not any(c.with_suffix(".py").is_file() or (c / "__init__.py").is_file() for c in cands):
            raise ValueError(f"no module {spec.module} in {codebase} (looked for {rel}.py and src/{rel}.py)")
    elif spec.kind == "typescript":
        base = codebase / spec.module.removeprefix("./")  # type: ignore[union-attr]
        if not any(base.with_suffix(x).is_file() for x in (".ts", ".tsx", ".mts", ".js", ".mjs")) and not base.is_file():
            raise ValueError(f"no file {spec.module}.ts (or .js) in {codebase}")
    elif spec.kind == "java":
        rel = spec.module.replace(".", "/") + ".java"  # type: ignore[union-attr]
        if not any((codebase / base / rel).is_file() for base in ("src/main/java", "src", ".")):
            raise ValueError(f"no class {spec.module} in {codebase} (looked for src/main/java/{rel})")
    elif spec.kind == "go":
        pkg = codebase / spec.module.strip("/")  # type: ignore[union-attr]
        if not pkg.is_dir() or not any(pkg.glob("*.go")):
            raise ValueError(f"no Go package {spec.module} in {codebase}")


def add_to_discovery(out: Path, codebase: Path, spec: NewAgent, model: str, upstream: str) -> str:
    """Add the agent to a project written by `discover` (or start one in `codebase`), and regenerate it."""
    check_code(codebase, spec)
    f = out / "discovery.json"
    d = Discovery.model_validate_json(f.read_text(encoding="utf-8")) if f.is_file() else \
        Discovery(repo=RepoInfo(root=str(codebase), name=codebase.name))
    ag = make_agent(spec, {a.id for a in d.agents})
    d.agents.append(ag)
    d.scenarios.append(first_scenario(ag.id, spec))
    build_plan(d, codebase)
    write_project(d, codebase, out, model=model, upstream=upstream)
    load_config(out)  # fail loudly if the result doesn't load
    return ag.id


def add_to_config(cfg_path: Path, codebase: Path, spec: NewAgent) -> str:
    """Add the agent to a hand-written crucible.yaml (a backup of the old file is kept as crucible.yaml.bak)."""
    check_code(codebase, spec)
    root = cfg_path.parent
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    agents: dict = data.get("agents") or {}
    if data.get("agent") and not agents:  # one unnamed agent becomes the first named one, so its suites keep it
        agents = {"agent": data.pop("agent")}
    data.pop("agent", None)
    ag = make_agent(spec, set(agents))
    if spec.kind == "command":
        entry = {"transport": "stdio", "command": spec.command.strip(), "cwd": _rel(codebase, root)}  # type: ignore[union-attr]
    else:
        d = Discovery(repo=RepoInfo(root=str(codebase), name=codebase.name), agents=[ag])
        plan = plan_agent(d, ag, codebase)
        if not plan.adapter_file or not plan.adapter_code:
            raise ValueError(plan.why)
        adapter = root / "adapters" / Path(plan.adapter_file).name
        adapter.parent.mkdir(parents=True, exist_ok=True)
        adapter.write_text(plan.adapter_code, encoding="utf-8")
        launcher = "npx tsx" if adapter.suffix == ".ts" else _python(codebase)
        env = {"PYTHONPATH": os.pathsep.join(["."] + (["src"] if (codebase / "src").is_dir() else [])), **plan.env}
        entry = {"transport": "stdio", "command": f"{launcher} {_rel(adapter, codebase)}", "cwd": _rel(codebase, root),
                 "env": env, "turn_timeout_s": 600}
    agents[ag.id] = entry
    data["agents"] = agents
    suites = data.setdefault("suites", {})
    suites[ag.id] = {"path": f"scenarios/{ag.id}", "runs": 3, "agent": ag.id}
    sc = first_scenario(ag.id, spec)
    sc_file = root / "scenarios" / ag.id / f"{sc.id}.yaml"
    sc_file.parent.mkdir(parents=True, exist_ok=True)
    sc_file.write_text(sc.yaml, encoding="utf-8")
    backup = cfg_path.with_name(cfg_path.name + ".bak")
    shutil.copyfile(cfg_path, backup)
    cfg_path.write_text(f"# Agent `{ag.id}` added in the AgentCrucible dashboard; the previous file is {backup.name}.\n"
                        + yaml.safe_dump(data, sort_keys=False, width=120), encoding="utf-8")
    try:
        load_scenarios(load_config(cfg_path))
    except Exception:
        shutil.copyfile(backup, cfg_path)  # leave the project as it was
        shutil.rmtree(sc_file.parent, ignore_errors=True)
        raise
    return ag.id


def _rel(p: Path, base: Path) -> str:
    return Path(os.path.relpath(p.resolve(), base.resolve())).as_posix()


__all__ = ["NewAgent", "add_to_config", "add_to_discovery", "make_agent", "first_scenario", "OUT_DIR"]


def remove_agent(project_root: Path, cfg_path: Path, codebase: Path, name: str, model: str, upstream: str) -> str:
    """Take an agent out of a project. Agents found by an import are switched off (a re-import offers them again);
    agents added by hand are deleted. Returns what happened, for the dashboard."""
    f = project_root / "discovery.json"
    if f.is_file():
        d = Discovery.model_validate_json(f.read_text(encoding="utf-8"))
        ag = d.agent(name)
        if ag is None:
            raise ValueError(f"no agent {name!r} in this project")
        if sum(a.include for a in d.agents) <= 1:
            raise ValueError("a project needs at least one agent: remove the whole project instead")
        if ag.added_by_hand:
            d.agents.remove(ag)
            d.scenarios = [s for s in d.scenarios if s.agent != name]
        else:
            ag.include = False
        build_plan(d, codebase)
        write_project(d, codebase, project_root, model=model, upstream=upstream)  # also deletes its unedited files
        load_config(project_root)
        return "deleted" if ag.added_by_hand else "excluded"
    data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    agents: dict = data.get("agents") or {}
    if name not in agents:
        raise ValueError(f"no agent {name!r} in this project" + ("" if agents else " (it has a single unnamed agent)"))
    if len(agents) <= 1:
        raise ValueError("a project needs at least one agent: remove the whole project instead")
    del agents[name]
    data["suites"] = {k: v for k, v in (data.get("suites") or {}).items() if (v or {}).get("agent") != name}
    backup = cfg_path.with_name(cfg_path.name + ".bak")
    shutil.copyfile(cfg_path, backup)
    cfg_path.write_text(f"# Agent `{name}` removed in the AgentCrucible dashboard; the previous file is {backup.name}.\n"
                        + yaml.safe_dump(data, sort_keys=False, width=120), encoding="utf-8")
    try:
        load_scenarios(load_config(cfg_path))
    except Exception:
        shutil.copyfile(backup, cfg_path)
        raise
    return "deleted"
