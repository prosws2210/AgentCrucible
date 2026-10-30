"""`discovery.json`: everything `crucible discover` found in a repository, and the user's review of it.

The scanner produces facts (each with file + line evidence); synthesis turns them into this agent map; the review UI
edits it; `apply` generates the test project from it; `--check` diffs a fresh scan against the approved copy.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

SCHEMA_VERSION = 1

Confidence = Literal["high", "medium", "low"]
Effect = Literal["read-only", "writes data", "destructive", "external call", "reads untrusted text"]
FactKind = Literal[
    "agent", "tool", "prompt", "model", "entrypoint", "mcp_server", "mcp_client", "skill", "subagent_edge",
    "datastore", "external_api", "vector_store", "env_var", "test_case", "llm_client",
]


class Evidence(BaseModel):
    file: str
    line: int
    snippet: str = ""


class Fact(BaseModel):
    """One thing a detector saw in the code, with where it saw it."""

    id: str = ""
    kind: FactKind
    name: str
    framework: str = "generic"
    evidence: list[Evidence]
    attrs: dict[str, Any] = Field(default_factory=dict)


class ModelRef(BaseModel):
    value: str | None = None  # a literal model name, if any
    env: str | None = None  # or the environment variable it comes from
    evidence: list[str] = Field(default_factory=list)


class PromptRef(BaseModel):
    file: str | None = None
    text: str | None = None  # first ~400 chars of an inline prompt
    evidence: list[str] = Field(default_factory=list)


class Entrypoint(BaseModel):
    kind: Literal["http", "cli", "code", "unknown"] = "unknown"
    route: str | None = None  # http: "POST /chat"
    command: str | None = None  # cli: "python -m app.main"
    module: str | None = None  # code: "app.agents.support"
    object: str | None = None  # code: "graph" or "build_graph"
    factory: bool = False  # `object` is a function that builds the agent
    evidence: list[str] = Field(default_factory=list)


class Agent(BaseModel):
    id: str
    name: str
    purpose: str = ""
    framework: str = "generic"
    language: Literal["python", "typescript", "javascript", "go", "java"] = "python"
    model: ModelRef = Field(default_factory=ModelRef)
    system_prompt: PromptRef = Field(default_factory=PromptRef)
    tools: list[str] = Field(default_factory=list)
    subagents: list[str] = Field(default_factory=list)
    mcp_servers: list[str] = Field(default_factory=list)
    entrypoint: Entrypoint = Field(default_factory=Entrypoint)
    datastores: list[str] = Field(default_factory=list)
    external_apis: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    evidence: list[str] = Field(default_factory=list)
    include: bool = True
    notes: list[str] = Field(default_factory=list)
    memory: str | None = None  # how it keeps state between turns or sessions (a checkpointer, a session store...)
    service: str | None = None  # in a monorepo: the folder of the service it belongs to
    auth_env: str | None = None  # its HTTP endpoint needs a token: the variable that holds a test token
    added_by_hand: bool = False  # added in the dashboard, not found by a scan: re-imports keep it
    app_url: str | None = None  # hand-added web service: where it runs (becomes APP_URL for the bridge)


class Tool(BaseModel):
    name: str
    description: str = ""
    kind: Literal["in-process", "mcp", "builtin", "unknown"] = "in-process"
    server: str | None = None  # the MCP server that provides it
    params: dict[str, str] = Field(default_factory=dict)
    effects: list[Effect] = Field(default_factory=list)
    touches: list[str] = Field(default_factory=list)  # "datastore:<id>", "api:<id>"
    sql_writes: list[str] = Field(default_factory=list)  # INSERT/UPDATE/DELETE statements in its body (for state checks)
    files: list[Literal["read", "write"]] = Field(default_factory=list)  # reads or writes files on disk
    mock: bool | None = None  # replace it with a canned reply in tests; None = mock it when it's destructive
    agents: list[str] = Field(default_factory=list)
    confidence: Confidence = "medium"
    evidence: list[str] = Field(default_factory=list)
    include: bool = True


class McpServer(BaseModel):
    name: str
    command: str | None = None  # how to start it locally
    url: str | None = None  # or where it already runs
    tools: list[str] = Field(default_factory=list)
    defined_here: bool = True  # implemented in this repository (vs. only configured)
    evidence: list[str] = Field(default_factory=list)
    include: bool = True


class Datastore(BaseModel):
    id: str
    kind: Literal["sqlite", "postgres", "mysql", "mongodb", "redis", "unknown"] = "unknown"
    url_env: str | None = None
    schema_files: list[str] = Field(default_factory=list)  # migrations, *.sql, ORM model files
    tables: dict[str, dict[str, str]] = Field(default_factory=dict)  # table -> column -> type
    evidence: list[str] = Field(default_factory=list)


class ExternalApi(BaseModel):
    id: str
    base_url: str | None = None
    base_url_env: str | None = None
    paths: list[str] = Field(default_factory=list)  # "POST /v1/charges"
    evidence: list[str] = Field(default_factory=list)
    kind: Literal["http", "queue"] = "http"  # a queue (Celery, Kafka, SQS...) is reported, not mocked over HTTP


class VectorStore(BaseModel):
    id: str
    kind: str
    evidence: list[str] = Field(default_factory=list)
    # tests answer from a snapshot of the repo's documents, a fixed passage, or the live store
    # (None: a snapshot when the repo has documents, else a fixed passage)
    test_with: Literal["snapshot", "mock", "live"] | None = None


class Skill(BaseModel):
    name: str
    description: str = ""
    file: str
    evidence: list[str] = Field(default_factory=list)


class Question(BaseModel):
    id: str
    text: str
    about: str | None = None  # "agent:<id>", "tool:<name>", "datastore:<id>"
    suggested: str | None = None
    options: list[str] = Field(default_factory=list)
    answer: str | None = None
    evidence: list[str] = Field(default_factory=list)


class DraftScenario(BaseModel):
    """A scenario `apply` will write, with the reason it was drafted (shown in review)."""

    id: str
    agent: str
    reason: str
    yaml: str
    include: bool = True
    edited: bool = False  # the reviewer changed the YAML; re-drafting keeps their version


class CodeFix(BaseModel):
    """A one-line change to the user's code, suggested by the planner and applied only if the reviewer accepts it."""

    id: str
    file: str
    line: int
    old: str  # the exact line as it is now
    new: str  # the line after the change
    add_import: str | None = None  # e.g. "import os", added at the top when missing
    why: str
    accept: bool = False


class ConnectionPlan(BaseModel):
    agent: str
    strategy: Literal["http", "stdio", "code", "manual"]
    why: str
    adapter_file: str | None = None
    adapter_code: str | None = None
    command: str | None = None
    url: str | None = None
    env_needed: list[str] = Field(default_factory=list)
    env_map: dict[str, str] = Field(default_factory=dict)  # app setting -> AgentCrucible variable
    env: dict[str, str] = Field(default_factory=dict)  # fixed values the agent gets, e.g. APP_URL
    warnings: list[str] = Field(default_factory=list)
    fixes: list[CodeFix] = Field(default_factory=list)


class RepoInfo(BaseModel):
    root: str
    name: str
    commit: str | None = None
    languages: dict[str, int] = Field(default_factory=dict)  # language -> files
    frameworks: list[str] = Field(default_factory=list)
    files_scanned: int = 0
    files_skipped: int = 0
    source: str | None = None  # the git URL it was cloned from
    dotenv: dict[str, list[str]] = Field(default_factory=dict)  # .env files the code may load -> variable names


class Discovery(BaseModel):
    version: int = SCHEMA_VERSION
    repo: RepoInfo
    agents: list[Agent] = Field(default_factory=list)
    tools: list[Tool] = Field(default_factory=list)
    mcp_servers: list[McpServer] = Field(default_factory=list)
    skills: list[Skill] = Field(default_factory=list)
    datastores: list[Datastore] = Field(default_factory=list)
    external_apis: list[ExternalApi] = Field(default_factory=list)
    vector_stores: list[VectorStore] = Field(default_factory=list)
    env_vars: list[str] = Field(default_factory=list)
    test_cases: list[dict[str, Any]] = Field(default_factory=list)  # sample prompts found in tests/evals
    questions: list[Question] = Field(default_factory=list)
    plans: list[ConnectionPlan] = Field(default_factory=list)
    scenarios: list[DraftScenario] = Field(default_factory=list)
    documents: list[str] = Field(default_factory=list)  # sample documents a RAG snapshot is built from
    facts: dict[str, Fact] = Field(default_factory=dict)
    synthesis: dict[str, Any] = Field(default_factory=dict)  # which model enriched it, if any, and what it was sent
    generator: dict[str, str] = Field(default_factory=dict)  # AgentCrucible and detector versions (audit trail)
    approved: bool = False

    def agent(self, agent_id: str) -> Agent | None:
        return next((a for a in self.agents if a.id == agent_id), None)

    def tool(self, name: str) -> Tool | None:
        return next((t for t in self.tools if t.name == name), None)
