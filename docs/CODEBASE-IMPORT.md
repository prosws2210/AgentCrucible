# Codebase import: plan

> Status: **implemented** (unreleased, targeting 0.3) · Owner: Shakti Swaroop Sahu
>
> Built: all three phases below, except the items listed under "Not built yet". Try it with
> `crucible discover examples/import-demo` or **Import codebase** in the dashboard.
>
> **Measured so far:** on a 22-repository labelled corpus (`tests/discover_corpus`), agents and tools were found with
> 100% recall and precision, MCP servers 100%, side-effect badges 98%. The detectors were tuned on this corpus, so
> expect lower numbers on unseen code. The "10 open-source repositories in under 10 minutes" target has not been
> measured yet.
>
> **Not built yet:** pull-request comments from `--check` (it prints markdown and exits non-zero); a published
> TypeScript adapter package (TypeScript agents get a generated `tsx` adapter instead); ready-made Go and Java
> adapters (they get an HTTP bridge or a scaffold); vector-store snapshots. The LangGraph, OpenAI Agents SDK and
> PydanticAI adapters are tested end to end with the real libraries; the CrewAI, LlamaIndex and LangChain
> `AgentExecutor` adapters have no tests yet.

Point AgentCrucible at a repository. It reads the code (without running it), finds every agent, tool, MCP server,
skill, prompt and model, drafts a complete test setup, and shows it to you for review. When you approve, it writes
the config and the tests, proves the setup works with a smoke run, and you can start regression testing.

---

## 1. The problem

Real projects rarely have one agent. A typical service has an orchestrator, a few specialist sub-agents, dozens of
tools (some in-process functions, some MCP servers), several prompts, a vector store, a database and two or three
third-party APIs. Today a user has to describe all of that by hand in `crucible.yaml`, write an adapter, and write
every scenario. That is the main reason teams don't adopt agent testing.

The import must work for **any kind of agent**: any framework or none, Python or TypeScript, a script, a web service
or an object inside a larger app, single-agent or multi-agent, RAG or tool-using.

### Goals

- From "here is my path" to a passing smoke run in **under 10 minutes**, for a typical repository.
- Find agents, tools and their side effects with high accuracy, and **show the evidence** for every claim.
- Ask the user only what the code cannot answer.
- Write nothing and run nothing until the user approves.
- Keep the result in sync as the code changes.

### Non-goals (for now)

- Agents that exist only in a vendor UI (no code in the repository).
- Fully automatic testing with no human review. The review step is the product, not a formality.
- Rewriting the user's agent code. The import may *suggest* small changes (for example reading a hard-coded base URL
  from the environment) and only applies them if the user accepts.

---

## 2. Design principles

1. **Evidence or a question.** Every fact the import shows links to a file and line. Anything without evidence is
   shown as a question, never as a guess.
2. **Deterministic first, LLM second.** Static analysis finds the facts; an LLM only interprets them. This keeps
   results stable, cheap and auditable.
3. **Reality is the judge.** After approval, one smoke run per scenario compares what the agents actually did with
   what the import predicted, and reports every mismatch.
4. **Private by default.** The scan runs locally, never executes repository code, never reads secrets, and the LLM
   step defaults to the local model.
5. **One source of truth.** Everything lives in `discovery.json`. The review screen edits it; the apply step generates
   files from it; re-scans diff against it.
6. **Extensible.** Each framework is a plug-in detector. A generic fallback covers frameworks nobody has written a
   detector for.

---

## 3. The user journey

### Step 1: Connect

- Dashboard: **Import a codebase** → choose a local folder (or, later, a Git URL).
- CLI: `crucible discover ./my-repo`.
- Before scanning, the user sees what will be read: file count by language, what is skipped (`.env*`, secrets,
  `node_modules`, virtualenvs, build output, binaries, anything in `.gitignore`), and which model will do the
  analysis (local Ollama by default; a hosted model only if the user picks one).

### Step 2: Scan (live progress)

"Scanned 1,240 files · found LangGraph, FastAPI, 2 MCP servers, Postgres, Pinecone…". No repository code runs.
Typical time: under a minute for 2,000 files plus the LLM step.

### Step 3: Review the agent map

The heart of the feature. Four parts:

1. **System diagram.** Entry points → agents → sub-agents → tools → the systems they touch (database, payment API,
   vector store, email). Clicking any node opens its card.
2. **Agent cards.** Name, purpose (one sentence), framework, model, system prompt (with a link to where it lives),
   tools, sub-agents and handoffs, memory/state, how it is started, and a confidence level.
3. **Tool cards.** Name, input schema, which agent uses it, what it touches, and a **side-effect badge**:
   `read-only`, `writes data`, `destructive`, `external call`, `reads untrusted text`. The badges drive test drafting
   and the safe defaults (destructive tools are mocked or blocked until the user says otherwise).
4. **Open questions.** Only what the code cannot answer, each with a suggested answer:
   - "`refund_order` writes to which database?" (suggested: `DATABASE_URL`, `orders` table)
   - "Which endpoint is the main entry point: `/chat` or `/v2/chat`?"
   - "Agent `planner` is created from a database row at runtime. Where can we construct it?"

Every card has include/exclude toggles and inline editing. Every fact shows its evidence (`app/agents/billing.py:42`).

### Step 4: Review the connection plan

For each agent: how AgentCrucible will run it and why, the environment variables and secrets it needs (names only,
taken from `.env.example`, settings classes and code), and the exact adapter files to be added, shown as a diff.

### Step 5: Review the draft tests

Starter scenarios grouped by agent, each with a one-line reason ("drafted because `delete_account` is destructive").
Accept, edit or delete each one. A coverage bar shows how many tools have at least one scenario.

### Step 6: Approve

"Looks good" then:

1. writes `crucible.yaml`, adapters, fixtures and scenarios into `agent-tests/` (or opens a pull request)
2. runs the connection check (model, every MCP server, every agent)
3. runs a **smoke run**: one attempt per scenario
4. shows the **discovery vs reality** report (section 9)
5. lands on the dashboard, ready for a baseline run

---

## 4. Architecture

```
            ┌──────────────┐   facts + evidence   ┌───────────────┐   agent map    ┌──────────────┐
 repo  ───▶ │  1 Scanner   │ ───────────────────▶ │ 2 Synthesizer │ ─────────────▶ │ discovery.json│
 (read-only)│  detectors   │                      │  (LLM, local) │                └──────┬───────┘
            └──────────────┘                      └───────────────┘                       │
                                                                                          ▼
 ┌──────────────┐  approve   ┌──────────────┐   files    ┌──────────────┐   results   ┌───────────────┐
 │ 3 Review UI  │ ─────────▶ │  4 Planner   │ ─────────▶ │  5 Apply     │ ──────────▶ │ 6 Verify      │
 │ (edits json) │            │ adapters,    │            │ config,      │             │ smoke run,    │
 └──────────────┘            │ fixtures,    │            │ scenarios    │             │ reality diff  │
                             │ scenarios    │            └──────────────┘             └───────────────┘
                             └──────────────┘
```

New modules in `src/agentcrucible/discover/`:

| Module | Job |
|---|---|
| `scan.py` | Walks the repository, applies ignore rules and secret filters, builds the file inventory |
| `parse.py` | tree-sitter parsing for Python, TypeScript and JavaScript; YAML/TOML/JSON config parsing |
| `detectors/*.py` | One plug-in per framework (section 5); each returns facts with evidence |
| `synthesize.py` | The LLM step: facts + snippets → agent map, with a strict JSON schema |
| `plan.py` | Connection strategy, fixtures, mocks and draft scenarios from the agent map |
| `apply.py` | Writes files, runs `validate`, the connection check and the smoke run |
| `reality.py` | Compares the smoke run's trajectories with the agent map |
| `schema.py` | Pydantic models for `discovery.json` (versioned) |

Server endpoints (all behind the existing token auth):

| Endpoint | Purpose |
|---|---|
| `POST /api/discover` | Start a scan of a path; returns a job id |
| `GET /api/discover/{job}` | Progress and the current `discovery.json` |
| `PATCH /api/discover/{job}` | Save review edits (JSON patch) |
| `POST /api/discover/{job}/apply` | Write files, then run validate, doctor and the smoke run |
| `GET /api/discover/{job}/reality` | The discovery vs reality report |

CLI:

```bash
crucible discover ./my-repo            # scan + synthesize, writes .crucible/discovery.json, opens the review UI
crucible discover ./my-repo --no-llm   # facts only (fast, deterministic)
crucible discover --apply              # apply an approved discovery.json from the terminal
crucible discover --check              # CI: report drift from the approved discovery.json (section 10)
```

---

## 5. Finding things: the detectors

### 5.1 How detectors work

Each detector receives the parsed repository and returns **facts**:

```json
{
  "kind": "tool",
  "name": "issue_refund",
  "framework": "openai-agents-sdk",
  "evidence": [{ "file": "app/tools/billing.py", "line": 42, "snippet": "@function_tool\ndef issue_refund(order_id: str, reason: str):" }],
  "attrs": { "params": { "order_id": "str", "reason": "str" }, "docstring": "Refund a delivered order." }
}
```

Fact kinds: `agent`, `tool`, `prompt`, `model`, `entrypoint`, `mcp_server`, `mcp_client`, `skill`, `subagent_edge`,
`datastore`, `external_api`, `vector_store`, `env_var`, `test_case`.

Parsing uses tree-sitter (Python, TypeScript, JavaScript first; Go and Java later), not regular expressions, so
decorators, call arguments and imports resolve correctly. Detectors follow imports one level to connect a tool
defined in one file with the agent that registers it in another.

### 5.2 Detector catalogue (Phase 1 in bold)

| Family | Signals |
|---|---|
| **Raw model calls** | OpenAI, Anthropic, Gemini, LiteLLM, Bedrock clients; calls with a `tools` parameter; the hand-written loop that executes `tool_calls` / `tool_use` |
| **LangGraph** | `StateGraph`, `add_node`, `add_edge`, `add_conditional_edges`, `compile`, `create_react_agent`, `ToolNode` |
| **LangChain** | `AgentExecutor`, `create_*_agent`, `@tool`, `StructuredTool`, `bind_tools` |
| **OpenAI Agents SDK** | `Agent(...)`, `function_tool`, `handoffs`, `Runner.run` |
| **CrewAI** | `Agent`, `Task`, `Crew`, `@tool`, `config/agents.yaml`, `config/tasks.yaml` |
| **PydanticAI** | `Agent(...)`, `@agent.tool`, `@agent.tool_plain`, `system_prompt` |
| **LlamaIndex** | `FunctionAgent`, `ReActAgent`, `AgentWorkflow`, `FunctionTool`, query engines as tools |
| **MCP** | Servers: `FastMCP`, `@mcp.tool`, `Server.list_tools`, TS `McpServer.tool`; clients: `ClientSession`, `streamablehttp_client`, `mcp.json`, `.mcp.json`, Claude Desktop config |
| **Vercel AI SDK, Mastra** | `generateText`/`streamText` with `tools`, `tool({...})`, Mastra `Agent` |
| Claude Agent SDK | `query(...)`, `ClaudeAgentOptions`, `allowed_tools`, custom tools, subagent definitions |
| AutoGen / AG2 | `AssistantAgent`, `UserProxyAgent`, `register_function`, group chats |
| Google ADK | `Agent`/`LlmAgent`, `tools=[...]`, `sub_agents` |
| Semantic Kernel | `Kernel`, `@kernel_function`, plugins |
| DSPy | `dspy.ReAct`, `dspy.Tool`, modules |
| **Skills and prompts** | `SKILL.md`, `.claude/skills/**`, prompt files (`*.prompt`, `prompts/**`), Jinja templates, system-prompt constants |
| **Entry points** | FastAPI/Flask/Starlette/Express/Next routes that accept messages; CLI entry points (`__main__`, `console_scripts`, `bin` in `package.json`); Dockerfile, docker-compose, Procfile |
| **Dependencies** | SQLAlchemy/Prisma/Drizzle/Django models and migrations, database URLs; `httpx`/`requests`/`fetch` base URLs; vector stores (pgvector, Chroma, Pinecone, Qdrant, Weaviate, FAISS); queues; `.env.example`, settings classes |
| **Existing evals** | Test files that call the agent, eval datasets (`*.jsonl`, `evals/**`), README examples |

### 5.3 The generic fallback

Any call to a model API with a `tools` argument is a **candidate agent**, even in a framework without a detector.
Any function whose schema is passed in that `tools` list is a candidate tool. This is what makes the import work for
in-house frameworks and new libraries on day one. Candidates found only by the fallback are shown with lower
confidence and a short explanation.

### 5.4 Side-effect classification

Each tool gets one or more badges. Static rules first, then the LLM for what rules can't decide:

| Badge | Static signals |
|---|---|
| `read-only` | Only `SELECT`, `GET`, file reads, retriever calls |
| `writes data` | `INSERT`/`UPDATE`, ORM `save`/`add`/`commit`, `POST`/`PUT`/`PATCH`, file writes |
| `destructive` | `DELETE`, `DROP`, `TRUNCATE`, `rm`, refunds, cancellations, payments, sending messages; names like `delete_*`, `cancel_*`, `refund_*`, `send_*` |
| `external call` | Network calls outside the service |
| `reads untrusted text` | Web fetch, email, uploaded documents, product data, repository files: anything a prompt injection could arrive through |

---

## 6. Understanding: the synthesis step

The LLM receives the facts and only the relevant snippets (never the whole repository), and must return a document
that matches the `discovery.json` schema. For large repositories it works in two passes: per-module summaries, then a
merge.

Rules given to the model and enforced by validation:

- Every agent, tool and edge must reference at least one fact id. Claims without a fact id are rejected and turned
  into questions.
- Purposes are one sentence, written for a reviewer.
- Unknowns go into `questions` with a suggested answer and the evidence that led to the question.
- Confidence is `high` (direct evidence), `medium` (inferred across files) or `low` (fallback detector or LLM-only).

Prompts and outputs of the synthesis step are cached by content hash, so re-scanning an unchanged repository costs
nothing.

### `discovery.json` (abridged)

```json
{
  "version": 1,
  "repo": { "root": ".", "commit": "a1b2c3d", "languages": ["python"], "frameworks": ["langgraph", "fastapi", "mcp"] },
  "agents": [
    {
      "id": "support",
      "name": "Support agent",
      "purpose": "Answers customer questions and handles refunds and cancellations.",
      "framework": "langgraph",
      "model": { "value": "gpt-4.1", "source": "env:OPENAI_MODEL", "evidence": ["f12"] },
      "system_prompt": { "file": "app/prompts/support.md", "evidence": ["f7"] },
      "tools": ["find_customer", "issue_refund", "search_products"],
      "subagents": ["billing"],
      "entrypoint": { "kind": "http", "route": "POST /chat", "evidence": ["f3"] },
      "confidence": "high",
      "include": true
    }
  ],
  "tools": [
    {
      "name": "issue_refund",
      "kind": "in-process",
      "schema": { "order_id": "string", "reason": "string" },
      "effects": ["writes data", "destructive"],
      "touches": ["datastore:postgres.orders"],
      "evidence": ["f42"]
    }
  ],
  "mcp_servers": [{ "name": "docs", "command": "python mcp/docs_server.py", "evidence": ["f51"] }],
  "datastores": [{ "id": "postgres", "kind": "postgres", "url_env": "DATABASE_URL", "schema_from": "alembic/versions" }],
  "external_apis": [{ "id": "stripe", "base_url_env": "STRIPE_API_BASE", "evidence": ["f60"] }],
  "questions": [
    { "id": "q1", "text": "Which endpoint is the main entry point: /chat or /v2/chat?", "suggested": "/v2/chat", "evidence": ["f3", "f4"] }
  ],
  "facts": { "f3": { "file": "app/api.py", "line": 18, "kind": "entrypoint" } }
}
```

---

## 7. Running each agent: the connection planner

### 7.1 Choosing how to run it

The planner picks the first option that applies and explains the choice:

| # | The agent is… | Connection | Status |
|---|---|---|---|
| 1 | Behind an HTTP endpoint that takes messages | `transport: http` (started per run, or an already-deployed URL with headers) | Built |
| 2 | A command-line program or script | `transport: stdio` with a generated adapter | Built |
| 3 | An object in code (a compiled graph, `Agent(...)`, a `Crew`) | Generated adapter that imports it (`module:object`) and calls it per turn | Built |
| 4 | Assembled at runtime from configuration or a database | Ask the user for a constructor; scaffold an adapter | Built |

For option 3, AgentCrucible ships small framework adapters: `agentcrucible.adapters.langgraph`, `.openai_agents`,
`.crewai`, `.pydantic_ai`, `.llamaindex`, `.langchain`, plus a TypeScript package for the Vercel AI SDK and Mastra. The
generated `agent-tests/adapter.py` is then a few lines:

```python
from agentcrucible.adapters.langgraph import serve
from app.agents.support import build_graph

serve(lambda: build_graph())   # one fresh graph per episode; turns arrive over stdio
```

### 7.2 Routing model calls through the gateway

The planner checks how each model client is built:

- Reads `OPENAI_BASE_URL` / `ANTHROPIC_BASE_URL` (or passes no base URL): works as is.
- Base URL from the app's own setting (`settings.llm_base_url`): the adapter sets that setting.
- Base URL or key hard-coded: the file and line are flagged with a one-line suggested change, applied only if the
  user accepts.
- A provider the gateway doesn't speak (Gemini native, Bedrock native): flagged, with the provider's
  OpenAI-compatible endpoint suggested.

### 7.3 Seeing in-process tools

Today the gateway records MCP tool calls. Most framework agents call ordinary functions, so the plan adds two layers:

1. **From model traffic, with no code changes.** Every model response already names the tool the model asked for,
   with its arguments. The gateway records these (`llm_call.tool_calls`), which is enough for "called", "not called",
   "order" and "not before turn N" checks.
2. **Tool tracing in the adapter (opt-in).** The framework adapter hooks the framework's own callbacks (LangChain
   callbacks, OpenAI Agents SDK tracing processors, CrewAI step callbacks, PydanticAI instrumentation, or
   OpenTelemetry GenAI spans) and posts `tool_call` / `tool_result` events to a new gateway endpoint,
   `POST /ep/{episode}/events`. Trajectories then show arguments, results, errors and timing for every tool, exactly
   like MCP tools. A thin `crucible_trace` decorator covers hand-written agents.

### 7.4 Safe defaults

- Tools marked `destructive` that touch real systems are **mocked or blocked** until the user chooses otherwise.
- External APIs become **HTTP mocks** with safe default replies.
- Secrets are never written to files. The plan lists required variable names; values come from the environment.

---

## 8. Clean environments and draft tests

### 8.1 Fixtures from what was found

| Found | Drafted |
|---|---|
| SQL database with migrations or ORM models | A seed file with a few realistic rows per table → SQLite or Postgres fixture per episode |
| Database without schema files | A question: "Point us to a schema dump or migrations" |
| External API calls | `http_mocks` with the endpoints the code uses and safe replies |
| Vector store / retriever | A small snapshot index from sample documents, or a mocked retriever returning fixed passages |
| A repository the agent edits | A `workspace` fixture |
| Files the agent reads | A `workspace` folder with sample files |

### 8.2 Scenario drafting rules

| Rule | Draft |
|---|---|
| Every tool | One scenario where using it correctly is the right answer (`trajectory.tool_called`) |
| `writes data` | Checks the state afterwards (`state.sql`, `http.called` with `body_contains`) |
| `destructive` | "Asks for confirmation first" (`not_before_turn`) and "refuses when it shouldn't" (`tool_not_called`) |
| `reads untrusted text` | A prompt-injection scenario with `inject:` on that tool |
| Multi-agent | Routing: "the right sub-agent handles it" |
| RAG | Grounded answer (`output.contains` the fact from the fixture), and "says it doesn't know" when nothing relevant is retrieved |
| Existing tests, eval sets, README examples | Reused as tasks, keeping their expected answers as checks |
| Every agent | A budget check (`max_llm_calls`, `max_tokens`) set from the smoke run |

Each draft carries its reason. The user approves, edits or deletes it. Drafts never reach CI without approval.

---

## 9. Proving it: the discovery vs reality report

After the smoke run, `reality.py` compares trajectories with the agent map:

| Finding | Example | Suggested action |
|---|---|---|
| Predicted tool never called | "`export_report` was never used in 14 episodes" | Add a scenario, or mark as unused |
| Unpredicted tool called | "`lookup_tax_rate` was called but isn't in the map" | Add it (one click) |
| Different model used | "Expected `gpt-4.1`, saw `gpt-4.1-mini`" | Check the model setting |
| Agent failed to start | "Import error in `app.agents.billing`" | Fix the adapter or the environment |
| Tool call failed | "`issue_refund` raised `KeyError`" | Check the fixture data |

A green report means the import is trustworthy, and the user can start a baseline run.

---

## 10. Keeping it in sync

- `crucible discover --check` in CI re-scans and diffs against the approved `discovery.json`.
- On a pull request: "New tool `bulk_refund` (destructive) has no tests. Draft scenarios added for review."
- Removed tools and agents mark their scenarios as stale.
- The dashboard shows **coverage**: agents and tools with at least one approved scenario.

---

## 11. Privacy and safety

- **No code execution during the scan.** Only parsing. The smoke run happens after approval, in the sandbox
  (ideally the container executor).
- **Secrets never leave the machine.** `.env*`, key files and anything matching secret patterns are skipped; string
  literals that look like keys are redacted before any snippet reaches the LLM.
- **Local model by default.** A hosted model is opt-in, and the review screen shows exactly which snippets were sent.
- **Nothing is written without approval.** The output is an `agent-tests/` folder or a pull request.
- **Audit trail.** `discovery.json` records which model and detector versions produced it.

---

## 12. Edge cases

| Case | Handling |
|---|---|
| Monorepo with many services | Scan per service; the review groups agents by service; the user picks which to import |
| Agents built at runtime from config or a database | Detected as a factory; question for a constructor; the smoke run confirms |
| Agent behind auth or a user session | HTTP transport with headers; a question for a test user or token variable name |
| Streaming or websocket endpoints | Adapter wraps the stream into a turn; websocket support scaffolded as a hand-written adapter |
| Long-running or async jobs | Adapter polls for completion with a timeout |
| Prompts in a database or prompt-management service | Question; prompt changes tested through `-e` overrides |
| Multiple models per agent (router, fallback) | All recorded; the model the gateway forces is configurable per agent |
| Non-Python/TypeScript code | Fallback detector on config and HTTP entry points; Go and Java detectors in Phase 3 |
| Very large repositories | Ignore rules, per-module synthesis, content-hash cache; a size estimate before the LLM step |

---

## 13. Delivery plan

### Phase 1: MVP (≈ 2–3 weeks)

- Scanner, tree-sitter parsing, secret filters, ignore rules
- Detectors: raw model calls, LangGraph, LangChain, OpenAI Agents SDK, CrewAI, PydanticAI, LlamaIndex, MCP,
  Vercel AI SDK, skills and prompts, entry points, dependencies, generic fallback
- Synthesis with schema validation and evidence rules; `discovery.json`
- Review UI (agent map, cards, questions, connection plan, draft tests)
- Apply: config, stdio/http adapters, framework adapters for LangGraph and OpenAI Agents SDK
- Smoke run and the discovery vs reality report

**Done when:** on 10 open-source agent repositories across frameworks, a reviewer gets to a green smoke run in
under 10 minutes with fewer than 5 edits on average.

### Phase 2 (≈ 2–3 weeks)

- Tool tracing (`/ep/{episode}/events`) and the remaining framework adapters
- Fixture drafting: database seeds, HTTP mocks, vector-store snapshots
- Better scenario drafting (reusing existing tests and eval sets); coverage on the dashboard

**Done when:** in-process tools show arguments and results in trajectories for every Phase 1 framework.

### Phase 3

- Git URL import; `--check` drift detection in CI with pull-request comments
- Import from traces (OpenTelemetry, LangSmith): real conversations become scenarios
- Detectors for Go and Java; more frameworks from the community

---

## 14. How we measure it

A benchmark of 20–30 open-source agent repositories across frameworks, each hand-labelled with its agents, tools,
side effects and entry points.

| Metric | Target (Phase 1) |
|---|---|
| Agents found (recall) | ≥ 95% |
| Tools found (recall) | ≥ 90% |
| False agents/tools (precision) | ≥ 90% |
| Side-effect badges correct | ≥ 85% |
| Edits per review | < 5 |
| Time from path to green smoke run | < 10 minutes |
| Questions asked per repository | < 5 |

The benchmark runs in CI, so detector changes can't silently get worse.

---

## 15. Risks

| Risk | Mitigation |
|---|---|
| Small local models produce weak synthesis | Evidence rules reject unsupported claims; questions instead of guesses; hosted model optional |
| Frameworks change APIs | Detectors are versioned plug-ins with fixture repos in the benchmark |
| Agents invisible to static analysis | Questions plus the smoke run, which observes what really happens |
| Users approve without reading | Destructive tools are mocked by default; drafts show their reasons; reality report highlights surprises |
| Repository code with side effects at import time | The scan never imports code; the smoke run runs in the sandbox after approval |

## 16. Open questions

1. Should the apply step default to a folder in the repository or a pull request?
2. Which hosted models should be offered for synthesis, and should snippets be shown before sending?
3. Should framework adapters live in the main package or as optional extras (`agentcrucible[langgraph]`)?
4. How should prompts stored outside the repository be versioned for regression tests?
