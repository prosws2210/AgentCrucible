# Adopting AgentCrucible

How a team puts its own agent and MCP servers under regression testing. Plan for **one day** to get a
first baseline and **one week** to have pull requests gated in CI.

Two complete, runnable references ship in `examples/`:

| Example | Agent shape | LLM API | Environment | What it shows |
|---|---|---|---|---|
| [`support-agent`](../examples/support-agent) | CLI process (stdio) | OpenAI Chat Completions | SQLite fixture per episode | Multi-turn conversations with a simulated customer, prompt injection, authorization |
| [`coding-agent`](../examples/coding-agent) | HTTP service | Anthropic Messages, streaming | Fresh copy of a Git repo per episode | Bug fixes and features verified by running the test suite, diff rules, destructive requests |

---

## 1. Install

```bash
pip install "agentcrucible @ git+https://github.com/prosws2210/AgentCrucible"   # CLI; `pip install agentcrucible` once released to PyPI
# container: docker build -t agentcrucible . (tagged releases also publish ghcr.io/prosws2210/agentcrucible), or the full stack: docker compose up
crucible init my-agent-tests        # scaffolds crucible.yaml and a first scenario
```

Requirements: Python 3.11+, Git (for workspace fixtures), and access to a model endpoint. For free local
testing, use Ollama: it serves both the OpenAI and the Anthropic API.

---

**Shortcut for an existing codebase:** `crucible discover ./my-repo --apply` finds the agents, tools, MCP servers,
databases and external APIs, writes everything in sections 2 to 4 below into `agent-tests/` for you to review, and
smoke-runs it (or use **Import codebase** in the dashboard). The rest of this guide explains what it generated and how to
adjust it.

## 2. Connect your agent

AgentCrucible records everything at two boundaries every agent already has: **LLM calls** and **MCP tool
calls**. Your agent only has to accept those two addresses from outside instead of hard-coding them.

### Pick a transport

| Your agent is… | Use | What AgentCrucible does per episode |
|---|---|---|
| A script / CLI / worker process | `transport: stdio` | Starts `command`, writes one JSON line per user turn to stdin, reads one JSON line back |
| A web service (FastAPI, Express, a deployed staging service…) | `transport: http` | POSTs every turn to `url` with the full history and the episode's addresses in `context` |

#### stdio

```yaml
agent:
  transport: stdio
  command: python agent.py
```

```text
in : {"type": "user", "content": "I want a refund"}       (one line per turn; {"type": "end"} at the end)
out: {"type": "assistant", "content": "Sure, which order?"}
```

The addresses arrive as environment variables:

| Variable | Value |
|---|---|
| `OPENAI_BASE_URL`, `OPENAI_API_KEY` | OpenAI-compatible gateway (the OpenAI SDK reads these automatically) |
| `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` | Anthropic Messages gateway (the Anthropic SDK reads these automatically) |
| `CRUCIBLE_MCP_<NAME>_URL` | One Streamable HTTP URL per MCP server in `crucible.yaml` |
| `CRUCIBLE_MODEL` | The model under test |
| `CRUCIBLE_WORKSPACE` | Path of the repo copy, if the scenario has a workspace |

Logs go to stderr; anything that isn't a JSON line on stdout is ignored.

#### http

```yaml
agent:
  transport: http
  url: http://127.0.0.1:8701/turn
  command: python agent_service.py --port 8701   # optional: started once per run; omit to test a deployed service
  headers: { Authorization: "Bearer ${STAGING_TOKEN}" }   # optional, sent with every turn
  ready_timeout_s: 60
  turn_timeout_s: 600
```

Every turn:

```json
POST /turn
{
  "episode_id": "fix-failing-test--2--a1b2c3",
  "messages": [{"role": "user", "content": "test_apply_discount is failing…"}],
  "context": {
    "openai_base_url": "http://127.0.0.1:53211/ep/<episode>/v1",
    "anthropic_base_url": "http://127.0.0.1:53211/ep/<episode>",
    "api_key": "agentcrucible",
    "model": "qwen2.5:7b",
    "mcp": {"workspace": "http://127.0.0.1:53211/ep/<episode>/mcp/workspace"},
    "workspace": "/tmp/crucible-xyz/workspace",
    "env": {"AGENT_PROMPT": "prompts/v2.md"}
  }
}
→ 200 {"content": "Fixed apply_discount; all tests pass."}
```

The service must build its LLM client and MCP connections from `context` for each request (most services
already build them per request or per session). See `examples/coding-agent/agent_service.py`: 90 lines,
official Anthropic SDK with streaming, no AgentCrucible imports.

### Model APIs

| Your agent calls… | Supported | Notes |
|---|---|---|
| OpenAI Chat Completions (`/v1/chat/completions`) | ✓ streaming and non-streaming | OpenAI, Azure-compatible proxies, OpenRouter, Groq, vLLM, Ollama |
| Anthropic Messages (`/v1/messages`) | ✓ streaming and non-streaming, `tool_use` | Anthropic API, Ollama ≥ 0.14 |
| OpenAI Responses API (`/v1/responses`) | ✓ streaming and non-streaming, function calls | OpenAI, Ollama (tested on 0.17). Send the full `input` each call: with `previous_response_id` the history lives at the provider, so cached replays can't tell turns apart |
| Gemini native, Bedrock native | ✗ not yet | Use their OpenAI-compatible endpoints, or open an issue |

Point the gateway at the real provider:

```yaml
model: claude-sonnet-4-5            # forced on every call, so the same suite can compare models
llm:
  upstream_base_url: https://api.openai.com/v1      # for OpenAI-format calls
  anthropic_base_url: https://api.anthropic.com     # for Anthropic-format calls
  cache: read_write
```

Keys come from the environment, never from the YAML file: `CRUCIBLE_LLM_API_KEY`, `CRUCIBLE_ANTHROPIC_API_KEY`.

### MCP servers

```yaml
mcp_servers:
  shop:      { command: python mcp/shop_server.py }
  workspace: { command: npx -y @your-org/mcp-repo-tools, env: { LOG_LEVEL: warn } }
  search:                                   # an already-running remote server
    url: https://mcp.example.com/mcp
    transport: http                         # Streamable HTTP (default) or sse
    headers: { Authorization: "Bearer ${SEARCH_MCP_TOKEN}" }   # ${VAR} is read from the environment
```

Every server is exposed to the agent through the MCP gateway, which records every call and can mock, block or
poison results (`environment.mocks`, `deny_tools`, `inject`).

- **Local servers** (`command`) start fresh per episode and receive `CRUCIBLE_DB` (SQLite path) or
  `CRUCIBLE_DB_URL` (Postgres URL), `CRUCIBLE_WORKSPACE` and `CRUCIBLE_HTTP_<NAME>_URL` when the scenario has them.
- **Remote servers** (`url`) are shared by every episode, so their state is not reset between tests: prefer
  read-only tools, a staging deployment, or `mocks` for tools with side effects. A wrong URL or token fails the
  episode at setup with the HTTP status (e.g. `HTTP 401: check its headers`); the dashboard's connection check
  shows the same.

---

## 3. Give each episode a clean world

| Need | Scenario field | Per episode |
|---|---|---|
| A database | `fixtures: { shop: fixtures/shop.sql }` | New SQLite file from the seed, path in `CRUCIBLE_DB` |
| A Postgres database | `fixtures: { shop: { postgres: fixtures/shop.sql } }` | `CREATE DATABASE` on `CRUCIBLE_POSTGRES_URL` (or `postgres.admin_url`), seeded, URL in `CRUCIBLE_DB_URL`, dropped afterwards |
| A third-party HTTP API | `http_mocks: { payments: [{ method: POST, path: /v1/charges, json: {…} }] }` | Canned responses at `CRUCIBLE_HTTP_PAYMENTS_URL` (agent and MCP servers); every request is recorded, unmatched ones get 404 |
| Files on disk | `workspace: { path: fixtures/inbox }` | Any directory works, not just code: a fresh copy per episode, checked with `state.file` |
| A repository | `workspace: { path: repos/service, ref: v1.4.0 }` | Fresh copy (or `git clone` + checkout of `ref`) with a baseline commit, path in `CRUCIBLE_WORKSPACE` |
| Fake a tool | `mocks: { send_email: { status: sent } }` | Tool returns this instead of running |
| Forbid a tool | `deny_tools: [drop_table]` | Call is blocked and recorded |
| Attack the agent | `inject: { read_file: "Ignore previous instructions…" }` | Text appended to the real tool output |

---

## 4. Write scenarios

Start from **real incidents and support tickets**, not invented cases. 20–50 good scenarios beat 500 generated ones.

```yaml
id: fix-failing-test
description: Fix the bug behind a failing test without touching the tests.
environment:
  workspace: { path: repos/calculator }
task: test_apply_discount is failing in this repository. Find the bug and fix it. Do not change the tests.
checks:
  - state.command: { run: python -m pytest, expect_exit: 0 }
  - state.git_diff: { changed: calc.py, not_changed: "tests/**", max_files: 1 }
  - trajectory.tool_called: { tool: run_tests, hard: false }
  - budget.max_llm_calls: 20
```

### Check reference

| Check | Asserts |
|---|---|
| `state.command` | A command run in the workspace (`run`, `expect_exit`, `contains`, `not_contains`, `timeout_s`); a leading `python` uses the runner's interpreter |
| `state.git_diff` | Files changed since the baseline: `changed` / `not_changed` globs, `max_files`, `max_lines` |
| `state.file` | A workspace file `exists` / is absent, `contains`, `not_contains`, `regex` |
| `state.sql` | Query the episode's SQLite or Postgres fixture (`expect` value or `expect_rows`) |
| `http.called` / `http.not_called` | Requests to a mocked HTTP API: `mock`, `method`, `path` glob, `body_contains`, `min` |
| `trajectory.tool_called` / `tool_not_called` / `call_order` / `not_before_turn` / `max_tool_calls` / `no_tool_errors` / `no_blocked_calls` | What the agent did, in which order and in which turn |
| `output.contains` / `not_contains` / `regex` | What the agent said |
| `budget.max_llm_calls` / `max_tokens` / `max_duration_s` / `max_cost_usd` | Cost and latency ceilings |
| `budget.min_llm_calls` | At least N model calls: catches an agent that answers without its model |
| `judge.rubric` | LLM judge 1–5; demoted to non-blocking if calibration κ < 0.6 |

Any check takes `hard: false` to report without failing the episode.

**Coding agents in particular:** always pair "it works" (`state.command` running the real or a hidden test)
with "it didn't cheat" (`state.git_diff` with `not_changed: tests/**`). An agent that edits the test to pass is
the most common failure, and only a diff check catches it.

---

## 5. Baseline and CI

```bash
crucible run --label baseline -k 5                  # on main
crucible run --label my-change -k 5 --compare baseline
```

- **k (runs per scenario)**: agents are non-deterministic. Use k ≥ 5 for gating; the report says
  "inconclusive, needs k≈N" when the evidence is too thin to call a single scenario.
- **Gate**: fails on statistically significant regressions (Fisher + Benjamini–Hochberg per scenario,
  bootstrap CI overall), not on noise.
- **Cost control**: `cache: read_write` records every model response (streamed ones included);
  `--cache replay` re-runs a suite from the recordings with no model calls at all. When tool output contains
  timestamps or durations, replay falls back to the response recorded at the same position (`hit-seq`).

GitHub Actions:

```yaml
- uses: prosws2210/AgentCrucible@main
  with:
    working-directory: agent-tests/
    runs: "5"
    llm-base-url: https://openrouter.ai/api/v1
    llm-api-key: ${{ secrets.OPENROUTER_KEY }}
```

On `main` it stores the baseline; on pull requests it compares, comments once and fails the check on regressions.

---

## 6. Team setup

| Need | Use |
|---|---|
| History, reports, start runs from a browser | `docker compose up` → dashboard at `http://localhost:8080/dashboard/` (frontend, API, Postgres, Ollama) |
| Large suites, nightly runs | Helm chart: sharded Indexed Job + merge/gate Job (`deploy/helm/agentcrucible`) |
| Audit your MCP servers before shipping them | `crucible mcp-audit --command "…"` or `--url https://… -H "Authorization: Bearer …"` (conformance, tool quality, fuzzing, security, behavior, latency) |
| Control who can use the dashboard | `CRUCIBLE_API_TOKEN` (full access) and `CRUCIBLE_VIEWER_TOKEN` (read-only) |
| Trust your LLM judges | `crucible label` → `crucible calibrate` (Cohen's κ against your own labels) |

---

## 7. Security model

- Agents and MCP servers under test run as **child processes of the runner**, with a fresh temp directory per
  episode. Run untrusted agents in the container or Kubernetes setup (non-root, read-only root filesystem,
  NetworkPolicy limiting egress to DNS and the model API).
- The API behind the dashboard only audits MCP servers declared in `crucible.yaml` and only reads fixtures
  inside the project; it never runs commands supplied in a request.
- The API and dashboard are **open unless a token is set**. With `CRUCIBLE_API_TOKEN` (and optionally a read-only
  `CRUCIBLE_VIEWER_TOKEN`), every `/api` call needs `Authorization: Bearer <token>` or the session cookie from the
  sign-in screen (HttpOnly, an HMAC of the role, never the token). There are no user accounts; for per-person
  access put your SSO proxy in front and keep the token on the proxy.
- Remote MCP header values (tokens) are never returned by the API.
- Model keys are read from environment variables, never stored in run artifacts.

---

## 8. First-week pilot plan

| Day | Outcome |
|---|---|
| 1 | Agent connected (stdio or http), MCP servers declared, one scenario passing locally |
| 2 | 10–20 scenarios from real incidents; first baseline at k = 5 |
| 3 | Security scenarios (injection via tool output, destructive requests, cross-tenant access); `mcp-audit` on every server |
| 4 | GitHub Action gating pull requests; cache enabled |
| 5 | Dashboard for the team; review flaky scenarios and runs-needed estimates; decide k and the gate policy |

## 9. Current limitations

| Not yet | Workaround |
|---|---|
| MySQL fixtures | SQLite or Postgres fixture, or a `state.command` check against your own test database |
| Resetting a remote MCP server's state between episodes | Point it at staging, mock side-effecting tools, or run it locally with `command` |
| User accounts / SSO in the dashboard | Shared tokens, or an SSO proxy in front of `frontend` |
| Gemini / Bedrock native APIs | Their OpenAI-compatible endpoints |
