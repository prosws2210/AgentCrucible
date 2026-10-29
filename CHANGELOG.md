# Changelog

All notable changes to AgentCrucible. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Codebase import:** `crucible discover <path | git URL>` reads a repository without running it and finds agents,
  tools (with side effects), MCP servers, sub-agents, prompts, databases, external APIs, vector stores, entry points and
  existing eval sets, across Python, TypeScript/JavaScript, Go and Java. Every finding cites its file and line; anything
  unproven becomes a question. An optional local-model pass writes descriptions.
- **Review and apply:** a draft `discovery.json`, a connection plan per agent and draft scenarios (uses, asks first,
  refuses, prompt injection, routing, RAG, reused evals). `--apply` writes `agent-tests/` (multi-agent `crucible.yaml`,
  adapters, SQL fixtures, HTTP mocks, scenarios), validates it and smoke-runs it with a discovery vs reality report.
- **Dashboard: Import codebase:** connect a folder or Git URL, review the system map, tools, questions, run plan and
  draft tests, approve, and see per-scenario results. Jobs survive a server restart.
- **Framework adapters:** `agentcrucible.adapters` for plain functions, LangGraph, OpenAI Agents SDK, PydanticAI,
  CrewAI, LlamaIndex and LangChain, with tool mocks, deny lists and injected tool output.
- **In-process tool tracing:** `POST /ep/{id}/events` records tool calls and results from adapters, and model-requested
  tool calls are recorded from every model API.
- **Drift check:** `crucible discover . --check` fails CI on a new agent or an untested destructive tool;
  `--update` re-drafts while keeping the review.
- **Trace import:** `crucible import-traces` turns OpenTelemetry (GenAI, OpenInference, OpenLLMetry), LangSmith or JSONL
  conversations into draft scenarios.
- **Named agents:** `agents:` in `crucible.yaml`, with `agent:` per suite or scenario.
- Budget checks accept `{max: N, hard: false}`.
- **Import, thorough mode:**
  - **Before a scan:** a preview of what will be read and skipped, and which model will see the snippets
    (`POST /api/discover/preview`).
  - **Model step:** batched by module for large repositories, cached by content (`CRUCIBLE_CACHE_DIR`), with every
    snippet sent listed in the review. A hosted model is optional.
  - **What it finds:** monorepo services, agent memory, endpoints behind auth (with a question for a test-token
    variable), prompts loaded from a prompt service, Django and Drizzle tables, queues (Celery, Kafka, SQS,
    RabbitMQ, RQ, BullMQ), README examples, and native Gemini and Bedrock clients.
  - **Drafted checks:**
    - tools that write get `state.sql` and `http.called` (with `body_contains`) checks
    - tools that use files get a fresh workspace
    - RAG agents get grounded-answer and "doesn't know" scenarios against a mocked retriever
    - budgets are set from the smoke run
  - **Review:**
    - per-tool "mock in tests"
    - edit a draft's YAML in place
    - suggested one-line code changes (e.g. a hard-coded model URL), applied only when accepted
    - a coverage bar
    - system-map nodes open their cards
  - **Apply:** a connection check before the smoke run. The reality report flags a different model, quotes the error
    from crashed agents' logs, and lists results per scenario (`GET /api/discover/{job}/reality`).
  - **CLI:** `crucible discover --apply --use-draft` applies a reviewed draft. `--check --report FILE` writes the drift
    report, and the `prosws2210/AgentCrucible/discover` action posts it as a pull-request comment. Removed tools mark
    their scenarios stale.

### Fixed
- Re-scans no longer read the generated `agent-tests/` folder as part of the user's code.
- Workspace copies skip virtualenvs and `node_modules`.

## [0.2.0] - 2026-10-28

### Added
- **Coding agents:** `workspace` fixture (fresh copy or `git clone` at a ref, with a baseline commit, per episode)
  and the `state.command`, `state.git_diff` and `state.file` checks.
- **HTTP agent services:** `transport: http`, started once per run or tested at an already-deployed URL, with
  per-turn `context` carrying the episode's gateway addresses and optional auth headers.
- **Model APIs:** Anthropic Messages (`/v1/messages`) and OpenAI Responses (`/v1/responses`) alongside Chat
  Completions, all with real streaming passthrough that is recorded, cached and replayable.
- **Cassette-style replay:** when tool output varies between runs (timestamps, durations), replay falls back to the
  response recorded at the same position (`hit-seq`).
- **Remote MCP servers:** `mcp_servers.<name>.url` (Streamable HTTP or SSE) with `${ENV}`-expanded headers, in runs,
  audits (`crucible mcp-audit --url … --header …`), the API and the connection check.
- **Postgres fixtures:** `fixtures: { shop: { postgres: seed.sql } }` creates and drops a fresh database per episode
  (`CRUCIBLE_POSTGRES_URL`); `state.sql` queries it.
- **HTTP mocks:** `environment.http_mocks` serves canned responses at `CRUCIBLE_HTTP_<NAME>_URL`, records every
  request, and the new `http.called` / `http.not_called` checks assert on them.
- **Authentication:** `CRUCIBLE_API_TOKEN` (full access) and `CRUCIBLE_VIEWER_TOKEN` (read-only) protect the API
  and dashboard; browser login via an HttpOnly session cookie.
- **Dashboard:** overview with onboarding, runs with live progress and in-app trajectories, scenarios, MCP audits,
  setup with a live connection check, login.
- **Website:** product site (how it works, use cases, features, compare, FAQ, docs), a 2-minute narrated walkthrough
  built from the real recorded runs, and a setup wizard that generates `crucible.yaml`, an agent adapter and a first
  scenario.
- **Docker Compose stack:** frontend, API, Postgres and an Ollama model server (GPU optional).
- **Releases:** tagged versions build wheels, a GitHub Release, Docker images on GHCR and (optionally) PyPI.

### Fixed
- Child processes no longer inherit an MCP server's stdio pipe (tests run from a tool hung for 120 s).
- Timestamps from SQLite are returned as UTC.

## [0.1.0] - 2026-10-28

First release: LLM and MCP gateways, sandboxed episodes with SQLite fixtures, user simulator, trajectory/output/
budget/judge checks, pass@k / pass^k with bootstrap CIs and Benjamini–Hochberg, MCP server audit, judge
calibration, HTML and Markdown reports, GitHub Action, Helm chart with sharded Indexed Jobs.

[0.2.0]: https://github.com/prosws2210/AgentCrucible/releases/tag/v0.2.0
[0.1.0]: https://github.com/prosws2210/AgentCrucible/commit/01029c7
