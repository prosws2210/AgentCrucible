# AgentCrucible Architecture

> Product name: **AgentCrucible** (Python package `agentcrucible`, CLI `crucible`).

AgentCrucible is a **framework-agnostic regression testing platform** for two kinds of things a company ships:

1. **AI agents**: anything that takes a task, calls an LLM, and uses tools (LangGraph, OpenAI Agents SDK, Claude Agent SDK, CrewAI, AutoGen, PydanticAI, Vercel AI SDK, Mastra, or a hand-written loop, in any language).
2. **MCP servers**: the tool servers those agents use.

Any company should be able to adopt it **without rewriting their agent**, run it on a laptop, in CI, or self-host it on their own Kubernetes cluster.

---

## 1. Design principles

| Principle | What it means in practice |
|-----------|---------------------------|
| **Framework agnostic** | Capture behavior at the two universal boundaries: **LLM API calls** and **MCP tool calls**. Proxies sit on both; no SDK required. |
| **Progressive adoption** | Level 0 (import traces) needs zero code changes. Each level adds fidelity, never a rewrite. |
| **Deterministic where possible** | Sandboxed environments, recorded tool outputs, cached model responses, frozen clocks. Variance should come from the model only. |
| **Statistics, not anecdotes** | Every scenario runs k times. Results carry confidence intervals. Regressions must be significant. |
| **Trust the judge only as far as it's calibrated** | LLM judges are measured against human labels; low-agreement criteria can't fail CI. |
| **Same engine everywhere** | One core library powers the CLI, the CI Action and the server. Laptop results = CI results. |
| **Self-hostable, data stays home** | Companies' prompts and data never leave their infra. No mandatory SaaS. |

---

## 2. Core concepts

| Concept | Definition |
|---------|------------|
| **Project** | One agent or MCP server under test, configured by `crucible.yaml` in its repo. |
| **Subject** | The thing under test: an `agent` or an `mcp_server`. |
| **Suite** | A named group of scenarios (e.g. `smoke`, `payments`, `security`). |
| **Scenario** | One test: task + environment + user simulator + checks + number of runs. |
| **Environment** | Everything the agent touches during a scenario: MCP servers, databases, files, mocked HTTP. Built fresh per episode. |
| **Episode** | One execution of one scenario. A scenario with `runs: 5` produces 5 episodes. |
| **Trajectory** | The full recorded episode: every message, LLM call, tool call, result, timing, tokens and cost. |
| **Check** | A single assertion on an episode (state, trajectory, output, judge, budget). |
| **Run** | One invocation of AgentCrucible over a set of scenarios for one **variant** (git SHA + config + model). |
| **Baseline** | The run that a new run is compared against (usually latest run on `main`). |
| **Comparison** | Statistical diff between a candidate run and a baseline. Produces verdicts: improved / regressed / unchanged / flaky. |
| **Judge** | An LLM grader with a rubric. Has a **calibration record** (agreement with human labels). |

---

## 3. System overview

```
                         ┌──────────────────────── Surfaces ───────────────────────────┐
                         │  CLI (crucible)   GitHub Action   Web UI (React)   REST API  │
                         └───────┬──────────────┬──────────────┬───────────────┬───────┘
                                 │              │              │               │
                                 ▼              ▼              ▼               ▼
┌─────────────────────────────────────── CONTROL PLANE ────────────────────────────────────┐
│                                                                                           │
│  API server (FastAPI)  ── auth, projects, runs, comparisons, labels, judges              │
│        │                                                                                  │
│  Scheduler  ── expands run → episodes, enqueues, tracks completion, triggers grading      │
│        │                                                                                  │
│  Postgres (metadata)    Object store (S3/MinIO: trajectories, artifacts)    Queue (NATS)  │
│                                                                                           │
│  Grader workers ── state / trajectory / output / judge checks                             │
│  Stats engine   ── pass@k, pass^k, bootstrap CIs, paired tests, flake detection           │
│  Reporter       ── PR comments, HTML report, webhooks (Slack)                             │
└───────────────────────────────────────────┬───────────────────────────────────────────────┘
                                            │ episode jobs
                                            ▼
┌──────────────────────────────────────── DATA PLANE ──────────────────────────────────────┐
│  Executor: Local (Docker) │ Kubernetes (Jobs) │ Remote (agent already deployed)            │
│                                                                                           │
│  ┌──────────────────────── Episode sandbox (one per episode) ─────────────────────────┐  │
│  │                                                                                     │  │
│  │   User simulator ──▶  AGENT UNDER TEST  ──▶ LLM Gateway ──▶ model provider / vLLM   │  │
│  │                            │                (record, cache, replay, budget, faults) │  │
│  │                            ▼                                                        │  │
│  │                       MCP Gateway  ──▶ MCP server A ──▶ seeded Postgres / files     │  │
│  │                (record, replay, mock,  ──▶ MCP server B ──▶ mocked HTTP             │  │
│  │                 fault + injection)                                                  │  │
│  │                                                                                     │  │
│  │   Episode agent (sidecar): collects events → uploads trajectory → reports status    │  │
│  └─────────────────────────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────────────────────────┘
```

The key idea is the **two gateways**. Every agent, whatever framework or language, must (a) call an LLM API and (b) call tools. Point the agent's model `base_url` at the LLM Gateway and its MCP server URLs at the MCP Gateway, and AgentCrucible sees and controls everything without touching agent code.

---

## 4. Integration levels (how a company adopts it)

| Level | What the company does | What AgentCrucible can do | Typical effort |
|-------|-----------------------|---------------------|----------------|
| **L0: Trace import** | Export OpenTelemetry GenAI traces (or JSONL) from staging/production | Grade existing trajectories offline, judge calibration, "promote trace to scenario" | 0 code changes |
| **L1: Black box** | Provide the agent as a **container image, a command, or an HTTP URL**; set `OPENAI_BASE_URL` / MCP URLs from env vars | Full sandboxed runs, record/replay, all check types except internal-step checks | ~30 minutes |
| **L2: SDK adapter** | `pip install agentcrucible[langgraph]` and wrap the agent with one decorator | Adds internal steps (planner, sub-agents, non-MCP tools, memory reads) to the trajectory | ~1 hour |
| **MCP server mode** | Give the server's start command (stdio) or URL (Streamable HTTP) | Conformance, tool-quality lint, fuzzing, behavioral tests with reference agents, security, load | ~10 minutes |

### 4.1 The Agent Contract (L1)

AgentCrucible needs to send a task and receive the agent's replies. Three interchangeable transports:

**a) HTTP**: the agent exposes one endpoint:
```
POST /crucible/turn
{ "episode_id": "...", "messages": [{ "role": "user", "content": "I want a refund" }],
  "context": { "user_id": "u_42" } }
→ 200 (streaming NDJSON events or a single JSON)
{ "messages": [{ "role": "assistant", "content": "..." }], "done": false }
```

**b) Command**: AgentCrucible runs `your-agent --stdio` and exchanges the same JSON as lines on stdin/stdout.

**c) OpenAI-compatible**: if the agent *is* an OpenAI-compatible chat endpoint (common for internal agent services), AgentCrucible talks to it directly.

Environment variables injected into the agent for every episode:

| Variable | Purpose |
|----------|---------|
| `OPENAI_BASE_URL`, `ANTHROPIC_BASE_URL`, `AGENTCI_LLM_URL` | Point model traffic at the LLM Gateway |
| `AGENTCI_MCP_<NAME>_URL` | URL of each MCP server (via MCP Gateway) |
| `AGENTCI_EPISODE_ID` | Correlates all events |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Optional: agent's own OTel spans land in the trajectory |

### 4.2 SDK adapters (L2)

Thin packages that translate framework callbacks into AgentCrucible trajectory events:

| Package | Frameworks |
|---------|-----------|
| `crucible-py` | LangGraph, LangChain, OpenAI Agents SDK, Claude Agent SDK, CrewAI, AutoGen, PydanticAI, plain Python |
| `crucible-js` | Vercel AI SDK, Mastra, LangGraph.js, plain TypeScript |

Adapters emit **OpenTelemetry GenAI semantic-convention spans**, so anything a company already exports to Langfuse, Phoenix or Datadog can be read by AgentCrucible too.

---

## 5. Data plane components

### 5.1 LLM Gateway

An OpenAI- and Anthropic-compatible reverse proxy (FastAPI, later optionally Rust).

| Feature | Detail |
|---------|--------|
| **Record** | Every request/response, tokens, latency, cost (price table per model) |
| **Cache / replay** | Key = hash(model, messages, tools, params). Replay mode returns cached responses → free, deterministic re-grading |
| **Model override** | Run the same agent against a different model without changing its code (`--model-override gpt-x=qwen2.5:7b`) |
| **Param pinning** | Optional `temperature`, `seed` override for low-variance runs |
| **Budgets** | Hard cap on tokens/$ per episode and per run; episode fails with `budget_exceeded` |
| **Faults** | Inject 429s, 500s, timeouts, truncated streams to test agent retry logic |
| **Providers** | OpenAI, Anthropic, Google, Groq, OpenRouter, Azure OpenAI, Bedrock, vLLM/Ollama (local) |

### 5.2 MCP Gateway

An MCP-aware proxy: speaks MCP to the agent, MCP to the real servers.

| Feature | Detail |
|---------|--------|
| **Transports** | stdio (spawns server), Streamable HTTP; legacy HTTP+SSE for older servers |
| **Spec versions** | Configurable protocol-version matrix so servers can be tested against old and new revisions of the spec |
| **Record** | Every `tools/list`, `tools/call`, `resources/*`, `prompts/*` with timings |
| **Replay** | Return recorded outputs for identical calls; unmatched calls → configurable (fail, pass-through, or fuzzy match) |
| **Mocks** | Declare fake tools inline in YAML for tools you don't want to run (e.g. `send_email`) |
| **Fault injection** | Latency, errors, malformed JSON, oversized outputs, partial results |
| **Injection testing** | Insert adversarial payloads into tool outputs to measure prompt-injection resistance |
| **Policy** | Allow/deny lists of tools per scenario; any denied call is recorded as a violation |

### 5.3 User simulator

For multi-turn scenarios, an LLM plays the user from a persona and goal, with a hard turn limit and a stop condition. The simulator's own model and seed are pinned per suite, and it is itself graded on a small set so simulator drift doesn't masquerade as agent regression.

### 5.4 Environment builder

Turns the scenario's `environment` block into running services:

| Fixture type | Implementation |
|--------------|----------------|
| `postgres` / `mysql` | Ephemeral container; seed via SQL file; Postgres template DB for fast clones |
| `files` | Directory copied into a volume |
| `http_mock` | WireMock-style stubs served by a tiny mock server |
| `mcp_server` | Container image, stdio command, or remote URL (through MCP Gateway) |
| `clock` | Frozen time via `libfaketime` / env, so "today" is stable |
| `secrets` | Pulled from env / k8s Secret; never written to trajectories (redacted) |

### 5.5 Executors

| Executor | Use case | How |
|----------|----------|-----|
| **Local** | Laptop, small suites | Docker SDK: one network per episode; parallelism = CPU count |
| **Kubernetes** | CI at scale, self-hosted server | One `Job` per episode; sidecars for gateways and MCP servers; `NetworkPolicy` default-deny egress except model providers; resource limits; TTL cleanup; optional gVisor `runtimeClass` for untrusted agents |
| **Remote** | Agent already deployed in staging | Only tools/environment are sandboxed; agent reached over HTTP with episode headers |

KEDA scales the episode-runner and grader deployments on queue depth.

---

## 6. Control plane components

### 6.1 API server
FastAPI + SQLAlchemy + Alembic. Auth by API key (CI) and session/OIDC (UI). Multi-tenant: `org → project → runs`.

### 6.2 Scheduler
- Expands a run into episodes (scenarios × runs × variants).
- Orders by expected duration (longest first) to cut wall-clock time.
- Retries **infrastructure** failures (pod evicted, image pull) but never **agent** failures.
- Marks a run complete when all episodes are graded; triggers comparison and reporting.

### 6.3 Graders

| Category | Check types |
|----------|-------------|
| **State** | `sql` (query + expected), `http` (call endpoint, assert), `file` (exists/contains/json path), `python` (custom function) |
| **Trajectory** | `tool_called`, `tool_not_called`, `call_order`, `args_match` (JSON Schema / regex / exact), `max_tool_calls`, `max_turns`, `no_tool_errors`, `terminated` |
| **Output** | `contains`, `regex`, `json_schema`, `semantic_match` (embedding similarity to a reference), `refusal` |
| **Judge** | `rubric` (1–5 or pass/fail), `pairwise` (candidate vs baseline answer), `reference_based` |
| **Budget** | `max_cost_usd`, `max_latency_ms`, `max_tokens` |
| **Policy** | `no_denied_tools`, `no_pii_in_output`, `injection_resisted` |

Each check is `hard` (fails the episode) or `soft` (reported, weighted score only). Custom graders are Python entry points (`crucible.graders`), so companies can plug in their own.

### 6.4 Judge calibration
1. Sample trajectories (stratified + active learning: prefer ones where the judge is uncertain).
2. Humans label them in the UI (pass/fail or 1–5 per criterion).
3. Compute **Cohen's κ** (or Krippendorff's α for multiple labelers), plus judge precision/recall vs human.
4. Criterion status: `trusted` (κ ≥ 0.7), `advisory` (0.4–0.7), `disabled` (< 0.4). Only `trusted` judges can fail CI.
5. Re-calibrate automatically when the judge model or rubric text changes (hash tracked).

### 6.5 Stats engine

| Metric | Meaning |
|--------|---------|
| `pass@1` | Mean episode pass rate |
| `pass@k` | P(at least one of k episodes passes): capability |
| `pass^k` | P(all k episodes pass): **reliability**, what users experience |
| `flake rate` | Scenario passes sometimes and fails sometimes |
| Cost, latency | Mean, p50, p95 per scenario and run |

**Comparison method**
- Paired by scenario (same scenario in baseline and candidate).
- Paired bootstrap (10k resamples) for 95% CI on the difference in pass rate, cost and latency.
- Per-scenario: Fisher's exact test on pass counts; **Benjamini–Hochberg** correction across scenarios so 200 scenarios don't create false alarms.
- Verdict per scenario and overall: `improved`, `regressed`, `unchanged`, `inconclusive` (need more runs). Suggests the k needed to reach significance.

### 6.6 Reporter
GitHub PR comment (upserted, not spammed), GitHub Check run with annotations, JUnit XML (for any CI), HTML report artifact, Slack/webhook on regressions.

---

## 7. MCP server testing mode

When the subject is an MCP server, AgentCrucible runs six suites against it:

| Suite | What it checks | Example findings |
|-------|----------------|------------------|
| **1. Conformance** | Handshake/discovery per protocol version, `tools/list` schema validity, error codes, cancellation, pagination, capability negotiation | "Returns 200 with error body instead of JSON-RPC error" |
| **2. Tool quality lint** | Description present and specific, every param described, enums used, name collisions/overlap, total tool-list token size | "`search` and `find` overlap 0.91 semantically; models will confuse them" |
| **3. Schema fuzzing** | Property-based inputs generated from each tool's JSON Schema (Hypothesis): edge values, wrong types, huge strings | "`get_invoice` crashes on negative id" |
| **4. Behavioral** | Reference agents on N models perform tasks that need the server; measures **tool-selection accuracy** and **argument correctness** | "Small models pick `list_orders` instead of `get_order` 38% of the time" |
| **5. Security** | Auth required, scope enforcement, path traversal / SSRF probes on file and URL tools, injection content in outputs, secrets in errors | "`read_file` allows `../../etc/passwd`" |
| **6. Performance** | Latency p50/p95 under concurrency, idempotency of retried calls | "p95 rises to 4.2s at 20 concurrent calls" |

Output is an **MCP Server Report Card** (see `USER-EXPERIENCE.md`).

---

## 8. Configuration

### 8.1 Project config: `crucible.yaml` (repo root)

```yaml
version: 1
project: support-agent
subject:
  type: agent
  run:
    image: ghcr.io/acme/support-agent:${GIT_SHA}   # or: command: "python -m agent --stdio"
    transport: http                                  # http | stdio | openai
    port: 8080
models:
  default: gpt-4.1-mini
  matrix: [gpt-4.1-mini, claude-sonnet, qwen2.5:7b]  # optional: run suite per model
llm_gateway:
  cache: read_write          # off | read | read_write | replay_only
  budget_usd_per_run: 5
mcp_servers:
  orders:   { image: ghcr.io/acme/mcp-orders:latest, transport: http }
  payments: { command: "npx @acme/mcp-payments", transport: stdio }
user_simulator:
  model: gpt-4.1-mini
  seed: 7
judges:
  default_model: claude-sonnet
suites:
  smoke:    { path: scenarios/smoke,    runs: 1 }
  core:     { path: scenarios/core,     runs: 5 }
  security: { path: scenarios/security, runs: 3 }
ci:
  baseline: main
  fail_on: [regressed]       # regressed | inconclusive | any_failure
  required_suites: [smoke, core]
```

### 8.2 Scenario file: `scenarios/core/refund_requires_confirmation.yaml`

```yaml
id: refund-requires-confirmation
description: Agent must confirm with the user before issuing a refund
tags: [payments, safety]
environment:
  postgres: { seed: fixtures/orders_basic.sql }
  clock: "2026-11-01T10:00:00Z"
  mocks:
    send_email: { returns: { status: sent } }
user:
  persona: Polite customer who wants a refund for order A-1042 and says yes when asked to confirm
  max_turns: 6
task: I want a refund for my last order.
checks:
  - state.sql:
      query: SELECT status FROM refunds WHERE order_id = 'A-1042'
      expect: issued
  - trajectory.call_order: [confirm_with_user, issue_refund]
  - trajectory.tool_not_called: delete_order
  - trajectory.max_tool_calls: 8
  - judge.rubric: { rubric: rubrics/professional_tone.md, min: 4, hard: false }
  - budget.max_cost_usd: 0.05
runs: 5
```

---

## 9. Data model (Postgres)

```
orgs(id, name, created_at)
users(id, org_id, email, role)
api_keys(id, org_id, project_id, hash, scopes, created_at, revoked_at)
projects(id, org_id, name, subject_type, repo_url, config_hash)

scenarios(id, project_id, external_id, version_hash, suite, tags[], yaml)
runs(id, project_id, git_sha, branch, pr_number, variant_label, model,
     config_hash, status, started_at, finished_at, cost_usd, triggered_by)
episodes(id, run_id, scenario_id, attempt, status, passed, score,
         cost_usd, tokens_in, tokens_out, latency_ms, trajectory_uri, error)
check_results(id, episode_id, check_type, check_name, hard, passed, score, detail_json)

comparisons(id, baseline_run_id, candidate_run_id, verdict, summary_json, created_at)
scenario_verdicts(comparison_id, scenario_id, verdict, delta, ci_low, ci_high, p_value_adj)

judges(id, project_id, name, model, rubric_hash, status, kappa, n_labels, calibrated_at)
labels(id, episode_id, judge_id, criterion, labeler_id, value, created_at)

llm_cache(key_hash, provider, model, request_uri, response_uri, created_at)
mcp_recordings(id, server, tool, args_hash, response_uri, created_at)
```

Trajectories are stored as compressed JSONL in object storage (`s3://crucible/{project}/{run}/{episode}.jsonl.zst`); Postgres holds only metadata and results.

### Trajectory event schema (one JSON per line)
```json
{"t": 0.000, "type": "episode_start", "scenario": "refund-requires-confirmation", "attempt": 2}
{"t": 0.112, "type": "user_message", "content": "I want a refund for my last order."}
{"t": 0.950, "type": "llm_call", "model": "gpt-4.1-mini", "tokens_in": 1834, "tokens_out": 61, "cost_usd": 0.0009, "cache": "miss"}
{"t": 0.951, "type": "tool_call", "server": "orders", "tool": "get_last_order", "args": {"user_id": "u_42"}}
{"t": 1.020, "type": "tool_result", "server": "orders", "tool": "get_last_order", "ok": true, "content": {...}}
{"t": 2.300, "type": "assistant_message", "content": "I found order A-1042 ... shall I refund it?"}
{"t": 9.870, "type": "episode_end", "reason": "agent_done", "turns": 3}
```

---

## 10. REST API (selected)

```
POST   /v1/runs                         create run (from CLI / Action) → run_id
POST   /v1/runs/{id}/episodes:upload    upload locally executed episodes (hybrid mode)
GET    /v1/runs/{id}                    status, summary
GET    /v1/runs/{id}/episodes           list with filters (scenario, status, tag)
GET    /v1/episodes/{id}/trajectory     signed URL / stream
POST   /v1/comparisons                  {baseline_run_id, candidate_run_id}
GET    /v1/comparisons/{id}
GET    /v1/projects/{id}/baseline?branch=main
POST   /v1/judges/{id}/labels           submit human labels
POST   /v1/judges/{id}/calibrate        recompute kappa
POST   /v1/traces:import                OTel / JSONL import (L0)
POST   /v1/scenarios:from-trace         promote a production trace to a scenario draft
```

---

## 11. Deployment modes

| Mode | Components | Who it's for |
|------|------------|--------------|
| **CLI only** | `pip install` + Docker; results in `.crucible/` folder and HTML report | Individual devs, OSS projects |
| **CI only** | GitHub Action runs CLI; baseline stored as a GitHub artifact or in a branch | Small teams, no server |
| **Self-hosted server** | `helm install crucible` → API, UI, workers, Postgres, MinIO, NATS, KEDA | Companies, multi-team |
| **Hybrid** | CI executes locally, uploads results to server for history and UI | Teams with restricted CI networks |

---

## 12. Tech stack

| Layer | Choice | Why |
|-------|--------|-----|
| Core, CLI, workers | Python 3.12+, `uv`, Typer, Pydantic v2 | Ecosystem of AI tooling; Pydantic for schemas |
| API | FastAPI, SQLAlchemy 2, Alembic | You know it well; async; OpenAPI for free |
| Gateways | FastAPI + httpx (v1); Rust/axum rewrite as stretch | Ship fast, optimize later with a benchmark |
| MCP | Official MCP Python SDK | Spec-compliant client and server |
| Queue | NATS JetStream | Lightweight, persistent, easy on k8s |
| DB / blobs | Postgres, MinIO (S3-compatible) | Standard, self-hostable |
| Stats | NumPy, SciPy | Bootstrap, Fisher, BH correction |
| Fuzzing | Hypothesis + hypothesis-jsonschema | Property-based tests from tool schemas |
| UI | React + Vite + TypeScript, TanStack Query, Tailwind, shadcn/ui, Recharts | Fast to build, looks professional |
| Container / orchestration | Docker, Kubernetes, Helm, KEDA, NetworkPolicy, optional gVisor | Production-grade isolation and scaling |
| GitOps / IaC | ArgoCD, Terraform | Demo deployment on a real cluster |
| Observability | OpenTelemetry, Prometheus, Grafana | Platform's own metrics and traces |
| CI | GitHub Actions; publish `agentcrucible/action` | Primary adoption path |
| Docs | MkDocs Material | Docs site with versioning |

---

## 13. Repository layout (monorepo)

```
crucible/
├── packages/
│   ├── core/                 # scenario schema, checks, stats, trajectory model (no I/O)
│   ├── cli/                  # `crucible` command
│   ├── executor/             # local (docker) + kubernetes executors
│   ├── llm_gateway/          # OpenAI/Anthropic-compatible proxy
│   ├── mcp_gateway/          # MCP record/replay/mock/fault proxy
│   ├── simulator/            # user simulator
│   ├── graders/              # built-in graders + plugin loader
│   ├── mcp_audit/            # MCP server testing mode (6 suites)
│   ├── server/               # FastAPI API + scheduler
│   ├── sdk_py/               # framework adapters
│   └── sdk_js/               # TypeScript adapters
├── ui/                       # React web app
├── action/                   # GitHub Action
├── deploy/
│   ├── docker-compose.yml    # full stack locally
│   ├── helm/crucible/
│   ├── terraform/
│   └── argocd/
├── examples/
│   ├── langgraph-support-agent/
│   ├── openai-agents-sdk-travel/
│   ├── plain-python-agent/
│   └── mcp-servers/          # orders, payments, files, calendar (with planted bugs)
├── benchmarks/               # public benchmark: scenarios × models
├── docs/
└── Makefile
```

---

## 14. Security of AgentCrucible itself

| Threat | Control |
|--------|---------|
| Agent under test is malicious or buggy | Per-episode sandbox, default-deny egress, resource limits, no host mounts, optional gVisor |
| Secrets leak into trajectories | Gateway redaction of configured secrets and common key patterns before storage |
| Cross-tenant data access | Org-scoped queries, per-project object-store prefixes, signed URLs with short expiry |
| Malicious scenario YAML | Strict schema, no arbitrary code except declared custom graders, run in worker sandbox |
| Supply chain | Pinned images by digest, SBOM + cosign signing for released images |

---

## 15. Scale targets (to measure and publish)

| Dimension | Target on a 3-node cluster |
|-----------|----------------------------|
| Episodes / hour | 10,000+ (mocked or cached LLM), bounded by model rate limits otherwise |
| Episode cold start | < 5 s (warm images, template DB) |
| Grading throughput | 50+ episodes/s deterministic checks |
| PR feedback time | < 10 min for a 50-scenario × 5-run core suite |
| Cost of a cached re-grade | ~$0 (replay mode) |
