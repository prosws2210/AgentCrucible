# Changelog

All notable changes to AgentCrucible. Versions follow [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Changed
- **License:** new versions are source-available under the Functional Source License (FSL-1.1-ALv2): any use except
  offering AgentCrucible, or something substantially similar, as a competing commercial product or service; each
  version becomes Apache-2.0 two years after its release. v0.2.0 and earlier remain Apache-2.0.

### Added
- **Report a bug:** a form in the site footer and the dashboard sidebar (phone header too) that mails the maintainer
  "BUG REPORTED : <project>" with the report, through Web3Forms when `BUG_REPORT_KEY` is set at build time (`.env` for
  Docker Compose, repository variable for GitHub Pages); without a key it opens a prefilled GitHub issue.
- **Test database servers in the connection check:** Setup checks the Postgres server when scenarios use Postgres
  fixtures and the Redis server when imported code uses Redis, and says how to set one when it's missing.
- **Updated walkthrough on /demo:** new chapters for importing a codebase, reviewing the plan, the knowledge graph and
  the smoke run on seeded test databases.
- **Python for the agents:** `python:` in `crucible.yaml`, a managed per-project environment
  (`crucible env [--install]`, `GET /api/env`, `POST /api/env/install`, **Setup → Python for the agents**) and an `envs`
  volume in Docker Compose. The connection check imports each agent's code and names the missing package; the smoke run
  is skipped with that message until it's installed, and **Check again and smoke-run** (`POST /api/discover/{id}/smoke`)
  retries it.
- **Cancel a run:** a Cancel button on running runs (`POST /api/runs/{id}/cancel`) stops its agent processes; runs cut
  off by a server restart show as "interrupted".
- **Why an episode crashed:** the last error line of the agent's log is in the episode error, and **Show log**
  (`GET /api/runs/{id}/logs/{name}`, redacted) shows the rest.
- **Class agents that take a task dict** get a working adapter when their code reads a message-like key
  (`user_message`, `task_description`, …); otherwise the scaffold lists the keys the code reads.

- **Redis for tests:** with `CRUCIBLE_REDIS_URL` (Docker Compose now starts a `redis` service) every episode gets its own
  empty numbered Redis database, emptied before and after; imported agents' Redis URL settings point at it.
- **Migrations and big schemas:** a Postgres fixture can run a `migrate` command (Alembic, Django, Prisma) before its
  seed, and the import drafts one for Alembic projects. Each distinct fixture is built once per run as a template
  database and copied for every episode. The import reads `pg_dump` schemas and numbered SQL migrations (with reference
  data beside them), follows `ALTER TABLE` column changes, and leaves out roles, grants and rows that can't fit
  (CHECK constraints, partitions, column lengths).
- **More kinds of agents:** an orchestrator with no agent class that a web route calls with its model-backed parts
  (`await run_turn(text=query, classifier=…)`) is found, owns the tools of its package, and gets an adapter that repeats
  the route's call. Agents that take a file (`document_path`) get the document the conversation names, and drafted
  tests use a sample from the repository's own test data. Agents get the database whose setting they read anywhere in
  their imports.

### Changed
- **Name -> function tables count as tools only when a tool call is dispatched through them** (`TOOLS[call.name]`), so
  lookup tables of loaders, formatters and card writers are no longer reported as tools.
- **The dashboard opens at once** after the first load in a tab, and refreshes behind the page; a dropped connection
  keeps the open page instead of replacing it.
- **Minimal environment for code under test:** agents, MCP servers and checks no longer inherit the server's
  environment. `inherit_env: [NAME]` on an agent or MCP server, or `CRUCIBLE_PASS_ENV`, passes variables through.
  Credential-like variables from the repository's `.env` are blanked in drafted configs.
- **Gate:** a run where more than `ci.max_error_rate` (default 0.2) of episodes crashed is "inconclusive", not a pass
  or a regression; a run where nothing ran says so.
- **Import review:** fewer, more relevant questions (only about included agents, their tools and real databases);
  scripts, benchmarks and test files no longer produce tools or datastores; evals and the "says it doesn't know"
  scenario are drafted only where they fit; functions that don't take a message aren't offered as chat agents;
  Postgres fixtures for Postgres code; scenarios whose fixtures are still scaffolds are skipped instead of failing.
- Faster review on big repositories (cached graph and documents, slimmer job payloads) and a model list cached for
  5 minutes.

### Fixed
- Model listing for Anthropic keys (`x-api-key`), sampling parameters a model rejects are dropped and retried, and the
  dashboard reconnects by itself after the API was unreachable.
- **Imported class agents actually run:** their adapters get the fixture and mock settings (`env_map`), traced tools,
  a chat model on the gateway when the constructor takes `llm=` (`chat_model()`), and the conversation so far with each
  message (`as_message()`). Drafted smoke tests require a model call (new `budget.min_llm_calls`), so an agent that
  answers without its model no longer passes.
- **Postgres fixtures from real repositories load:** only the agents' own service's schema files, no one-off data
  scripts, psql-only syntax left out, `search_path` respected, and drafted rows that follow the schema's names, types
  (UUID, arrays, booleans) and foreign keys. Drafted tasks name ids that exist in those rows, and leave out optional
  inputs that would steer the agent to another tool.
- "Uses" scenarios have a simulated user who supplies details when the agent asks for them; the simulator and the judge
  drop parameters a model rejects (`temperature` on newer Claude models), like the gateway.
- Agents keep one event loop for the whole conversation, so async clients don't fail with "Event loop is closed" on
  the second turn.
- Code under test starts with tracing and telemetry off (LangSmith, Langfuse, OpenTelemetry, Sentry, ...), even when it
  loads the repository's `.env` at run time.
- `trajectory.no_tool_errors` also catches tools that return their failure (`{"success": false, "error": ...}`).
- Cancel: episodes cut short are not counted as failures, and a cancelled run gets no comparison or gate verdict.
  "Run again" compares with the run it repeats.
- Dashboard: run page notices redesigned, the scenario table no longer clips its columns, the run form counts agents and
  leaves skipped scenarios out of its estimate, pages revalidate after an upgrade (`Cache-Control: no-cache`), and the
  knowledge graph's side panel wraps long paths.
- **Import with Docker on Windows:** set `CRUCIBLE_IMPORT_DIR` in `.env` to the folder holding your repositories and
  paste paths exactly as Windows shows them (`D:\code\my-repo`); they're found at `/import/my-repo`. A path the
  container can't see now says how to mount it instead of "Can't preview this folder".
- **Descriptions with OpenAI or Claude:** the import's Options can use an OpenAI or Anthropic API key instead of the
  local model. Requests are bigger and run four at a time; Claude is called through the Anthropic SDK
  (`claude-opus-5-5` by default, with server-side fallback on a refusal). The key is used for that import only and is
  never written to disk.
- **The review opens before the model finishes:** the map comes from the code alone and descriptions fill in from the
  background, so a slow local model no longer holds up the review.
- **Knowledge graph:** every import writes `agent-tests/knowledge-graph.json` and a self-contained
  `knowledge-graph.html` (no server or network): files and their imports, agents, tools, MCP servers, prompts, databases,
  APIs and vector stores, and what uses what, each with its file and line. Click an agent or MCP server to see everywhere
  it's used. `crucible graph [path] [--rescan]` rebuilds it; the dashboard has a **Knowledge graph** page and an import
  review tab, served by `GET /api/graph`, `/api/graph.html` and `/api/discover/{id}/graph[.html]`.
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

- **Import: everything in the plan built:**
  - **Pull requests:** `crucible discover --apply --pr` (and "Also open a pull request" in the dashboard) commits
    `agent-tests/` and accepted code changes to a new branch from HEAD with git plumbing (the working tree, index and
    current branch are untouched), pushes it and opens the pull request with the GitHub CLI when it's logged in.
  - **TypeScript, Go and Java runtimes:** `packages/adapters-js` (`@agentcrucible/adapters`), `packages/adapters-go`
    and `packages/adapters-java` (one dependency-free file that also starts Spring Boot apps without their web
    server and calls a bean). Generated adapters carry a copy. Tested end to end with the Vercel AI SDK, Mastra,
    go-openai, a plain Java class and a Spring Boot bean.
  - **Real-library tests for CrewAI, LlamaIndex and LangChain `AgentExecutor`**, next to LangGraph, OpenAI Agents SDK
    and PydanticAI. **A Google ADK adapter** (`agentcrucible.adapters.google_adk`) routes ADK's Gemini calls through
    the gateway with ADK's LiteLlm and reads tool calls from its event stream.
  - **Import progress you can follow:** a live elapsed timer, the expected time ("usually 5–10 minutes on a local
    model"), which test is running, a progress bar and the time left, and how long since the last update.
  - **Document snapshots for RAG:** the import indexes the repo's documents (`docs/`, `data/`, `knowledge/`...) into
    `fixtures/documents-snapshot.json`; a retriever mocked with `{snapshot: ..., k: 3}` answers each query with the
    best-matching passages (BM25, same results in every runtime). The reviewer can still choose fixed passages or the
    live store.
  - **One-click "add it"** for tools the smoke run saw but discovery missed (`POST /api/discover/{job}/tools`); the
    next approve drafts their tests.
  - **Several models per agent:** `agents.<name>.model` and `model_map` (requested model -> model to use, for routers
    and fallbacks), shown on the agent's page.
  - **Benchmark on real repositories:** `benchmarks/import_bench.py` imports 10 pinned open-source agent repositories
    in a throwaway container and measures questions, reviewer edits and time to a smoke run
    ([results](benchmarks/RESULTS.md): 0 edits and 2.3 questions per repository; 3 of 10 smoke runs without agent
    errors on a slow local model, so the Phase 1 target is not met yet).
- **Projects and agents in the dashboard:**
  - One server shows several projects (one `crucible.yaml` with any number of agents each): the one it was started in,
    every approved import, and folders added by path. A switcher in the sidebar picks one; the list is kept in
    `.crucible/projects.json`. Imports approved before this release are picked up from their saved jobs.
  - **Agents** page and a page per agent: how it's connected (adapter, command, environment), what it uses (tools with
    side effects, model, memory, sub-agents), its tests with their latest results, its own runs, and buttons to run
    just its tests.
  - **Add agents**: import a codebase, or add one agent by hand (Python function or framework object, TypeScript
    export, web service, or stdio command) with its first test, to the current project or another codebase. It uses
    the same planner and adapters as `discover`; re-imports keep agents added by hand. Agents can be removed again.
  - Overview lists every agent with its pass rate; runs can target one agent (`POST /api/runs {agent}`) and compare
    against the latest run of the same scope; scenarios and run results show which agent they belong to; Setup
    checks every agent.
  - `/start/` offers importing a codebase first, and setting up one agent by hand second.

### Fixed
- **Big repositories:** listing a 3,900-file repo on a Docker Desktop mount took 40 s and is now about 3 s (no stat per
  entry, sizes fetched in parallel, files read in parallel); analysis runs each module's syntax tree walk once.
- **Model step on big repositories:** requests are sized to fit a local model's 4,096-token window (prompts were cut
  from the front, losing the instructions), only tools without a docstring are sent, and one timed-out request no
  longer throws away the others.
- **Agents built on a repository's own base class** (`class InvoiceAgent(BaseAgent)`, where `BaseAgent.__init__` takes
  `tools`) are found, with their tools; agents and tools in test files and `scripts/` are no longer offered as the
  product's, and private one-call model helpers are left unticked.
- **Monorepos:** a service with its own `pyproject.toml` or `requirements.txt` is imported from its folder
  (`src.agents.x`, not `services.ai-api.src.agents.x`), so adapters can import it and cross-file tools resolve.
- LlamaIndex (and older LangChain / LiteLLM) agents read `OPENAI_API_BASE`, so their calls skipped the gateway; it
  is now set next to `OPENAI_BASE_URL`.
- Agent commands like `npx`, `go` or `mvn` failed to start on Windows (`.cmd` files on PATH).
- An agent that raised an exception (an "[agent error]" reply from an adapter, or an unfinished scaffold) counted as an
  answer that failed its checks; it is now an agent error in the run and the reality report.
- LangGraph graphs with a runtime context (`context_schema`) or an input that isn't a conversation, and OpenAI Agents
  with a typed context (`Agent[Context]`), ran without a context and crashed; the adapters now build one from the
  declared type (defaults, plus test values for required fields).
- Found by the benchmark on real repositories: tool lists imported from another module (`ToolNode(TOOLS)`), tools bound
  inside a graph node (`bind_tools([tools.x])`), generic agents (`Agent[Context](...)`), `handoff(agent=...)` calls,
  crew members built by factory methods, agents named after a generic variable (`graph`, `agent`), agents defined in
  test files (now left out), and questions the code already answers ("what is the purpose of...").
- CrewAI: tools defined on a crew's members are now tested through the crew. LangChain: `langchain_classic` and
  `AgentExecutor(agent=create_tool_calling_agent(...))` written inline are recognised.
- An approved import didn't appear anywhere in the dashboard: it is now a project there.
- Re-applying an import left the tests and adapters of removed agents or switched-off drafts on disk (unedited ones
  are now deleted).
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
