# Changelog

All notable changes to AgentCrucible. Versions follow [Semantic Versioning](https://semver.org/).

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
