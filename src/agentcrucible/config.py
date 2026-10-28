"""Project config (crucible.yaml) and scenario schema."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

CONFIG_FILENAME = "crucible.yaml"


class AgentSpec(BaseModel):
    """How to reach the agent under test.

    stdio: `command` is spawned once per episode; one JSON line in, one JSON line out per turn.
    http:  each turn is POSTed to `url` with the full history and the episode's gateway URLs in `context`.
           If `command` is set, AgentCrucible starts the service once per run and waits for it;
           otherwise the service is expected to be running already (e.g. a staging deployment).
    """

    transport: Literal["stdio", "http"] = "stdio"
    command: str | None = None
    url: str | None = None
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)
    headers: dict[str, str] = Field(default_factory=dict)  # http: e.g. an auth token for a staging service
    turn_timeout_s: float = 180.0
    ready_timeout_s: float = 60.0

    @model_validator(mode="after")
    def _check(self) -> "AgentSpec":
        if self.transport == "stdio" and not self.command:
            raise ValueError("agent.command is required for stdio transport")
        if self.transport == "http" and not self.url:
            raise ValueError("agent.url is required for http transport")
        return self


class McpServerSpec(BaseModel):
    """An MCP server the agent can use. Spawned fresh (stdio) per episode."""

    command: str
    cwd: str | None = None
    env: dict[str, str] = Field(default_factory=dict)


class LLMSettings(BaseModel):
    upstream_base_url: str = "http://localhost:11434/v1"  # OpenAI-compatible (chat/completions)
    api_key: str = "ollama"
    # Anthropic Messages upstream; default derives from upstream_base_url (Ollama serves both APIs)
    anthropic_base_url: str | None = None
    anthropic_api_key: str | None = None
    # off: always call upstream; read_write: reuse + store; replay: only cached responses
    cache: Literal["off", "read_write", "replay"] = "off"
    price_per_1k_input: float = 0.0
    price_per_1k_output: float = 0.0


class HelperModel(BaseModel):
    """Model used by the user simulator or the judge (not recorded as agent cost)."""

    model: str = "qwen2.5:3b"
    base_url: str = "http://localhost:11434/v1"
    api_key: str = "ollama"
    temperature: float = 0.3


class SuiteSpec(BaseModel):
    path: str
    runs: int = 3


class CISettings(BaseModel):
    fail_on: list[Literal["regressed", "inconclusive", "any_failure"]] = Field(
        default_factory=lambda: ["regressed"]
    )
    alpha: float = 0.05


class ProjectConfig(BaseModel):
    version: int = 1
    project: str
    agent: AgentSpec
    model: str = "qwen2.5:7b"
    llm: LLMSettings = Field(default_factory=LLMSettings)
    mcp_servers: dict[str, McpServerSpec] = Field(default_factory=dict)
    simulator: HelperModel = Field(default_factory=HelperModel)
    judge: HelperModel = Field(default_factory=lambda: HelperModel(temperature=0.0))
    suites: dict[str, SuiteSpec] = Field(default_factory=dict)
    ci: CISettings = Field(default_factory=CISettings)

    root: Path = Field(default=Path("."), exclude=True)

    def resolve(self, p: str | None) -> Path | None:
        if p is None:
            return None
        path = Path(p)
        return path if path.is_absolute() else (self.root / path)


# ---------------------------------------------------------------- scenarios


class UserSimSpec(BaseModel):
    persona: str
    max_turns: int = 4


class WorkspaceSpec(BaseModel):
    """A repository copied fresh for every episode (for coding agents)."""

    path: str  # directory or git repo, relative to the scenario file or project root
    ref: str | None = None  # git ref to check out when `path` is a git repo


class Environment(BaseModel):
    # server name -> SQL seed file; a fresh SQLite DB is built per episode
    fixtures: dict[str, str] = Field(default_factory=dict)
    # fresh copy of a repo per episode, exposed as CRUCIBLE_WORKSPACE to the agent and MCP servers
    workspace: WorkspaceSpec | None = None
    # tool name -> result returned instead of calling the real server
    mocks: dict[str, Any] = Field(default_factory=dict)
    # tool name -> text appended to the real tool output (prompt-injection testing)
    inject: dict[str, str] = Field(default_factory=dict)
    # tool names the agent must never call; calls are blocked and recorded
    deny_tools: list[str] = Field(default_factory=list)


class Check(BaseModel):
    """One assertion. Written in YAML as `- kind.name: params`."""

    kind: str  # state | trajectory | output | judge | budget
    name: str
    params: Any = None
    hard: bool = True

    @property
    def label(self) -> str:
        return f"{self.kind}.{self.name}"


class Scenario(BaseModel):
    id: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    task: str
    user: UserSimSpec | None = None
    environment: Environment = Field(default_factory=Environment)
    checks: list[Check]
    runs: int | None = None

    source: Path | None = Field(default=None, exclude=True)

    @field_validator("checks", mode="before")
    @classmethod
    def _parse_checks(cls, raw: Any) -> Any:
        out = []
        for item in raw or []:
            if isinstance(item, dict) and "kind" in item:
                out.append(item)
                continue
            if not isinstance(item, dict) or len(item) != 1:
                raise ValueError(f"each check must be a single-key mapping like `- trajectory.tool_called: x`, got {item!r}")
            key, params = next(iter(item.items()))
            if "." not in key:
                raise ValueError(f"check key must be `kind.name`, got {key!r}")
            kind, name = key.split(".", 1)
            hard = True
            if isinstance(params, dict) and "hard" in params:
                params = dict(params)
                hard = bool(params.pop("hard"))
            out.append({"kind": kind, "name": name, "params": params, "hard": hard})
        return out

    @field_validator("id")
    @classmethod
    def _id(cls, v: str) -> str:
        if not v.replace("-", "").replace("_", "").isalnum():
            raise ValueError("scenario id may contain only letters, digits, - and _")
        return v


# ---------------------------------------------------------------- loading


def find_config(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        return cur
    for d in [cur, *cur.parents]:
        f = d / CONFIG_FILENAME
        if f.exists():
            return f
    raise FileNotFoundError(f"{CONFIG_FILENAME} not found in {cur} or its parents (run `crucible init`)")


def load_config(path: Path | None = None) -> ProjectConfig:
    f = find_config(path)
    data = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
    cfg = ProjectConfig.model_validate(data)
    cfg.root = f.parent
    # ${VAR} in agent headers, so tokens for staging services stay out of the file
    cfg.agent.headers = {k: os.path.expandvars(v) for k, v in cfg.agent.headers.items()}
    # Deployment-time override, e.g. inside Kubernetes where the model server has another address.
    if url := os.environ.get("CRUCIBLE_LLM_URL"):
        cfg.llm.upstream_base_url = cfg.simulator.base_url = cfg.judge.base_url = url
    if url := os.environ.get("CRUCIBLE_ANTHROPIC_URL"):
        cfg.llm.anthropic_base_url = url
    if key := os.environ.get("CRUCIBLE_ANTHROPIC_API_KEY"):
        cfg.llm.anthropic_api_key = key
    if key := os.environ.get("CRUCIBLE_LLM_API_KEY"):
        cfg.llm.api_key = cfg.simulator.api_key = cfg.judge.api_key = key
    if model := os.environ.get("CRUCIBLE_MODEL"):
        cfg.model = model
    if helper := os.environ.get("CRUCIBLE_HELPER_MODEL"):
        cfg.simulator.model = cfg.judge.model = helper
    return cfg


def load_scenarios(cfg: ProjectConfig, suite: str | None = None, ids: list[str] | None = None) -> list[tuple[Scenario, int]]:
    """Return (scenario, runs) pairs for the requested suite(s)."""
    suites = cfg.suites if suite is None else {suite: cfg.suites[suite]} if suite in cfg.suites else None
    if suites is None:
        raise KeyError(f"unknown suite {suite!r}; known: {', '.join(cfg.suites)}")
    out: list[tuple[Scenario, int]] = []
    seen: set[str] = set()
    for spec in suites.values():
        base = cfg.resolve(spec.path)
        files = sorted(base.rglob("*.yaml")) if base.is_dir() else [base]
        for f in files:
            sc = load_scenario_file(f)
            if ids and sc.id not in ids:
                continue
            if sc.id in seen:
                continue
            seen.add(sc.id)
            out.append((sc, sc.runs or spec.runs))
    return out


def load_scenario_file(f: Path) -> Scenario:
    try:
        data = yaml.safe_load(f.read_text(encoding="utf-8"))
        sc = Scenario.model_validate(data)
    except Exception as e:  # add file context
        raise ValueError(f"{f}: {e}") from e
    sc.source = f
    return sc
