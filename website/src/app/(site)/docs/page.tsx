import type { Metadata } from "next";
import Link from "next/link";
import { DocsToc } from "@/components/site/DocsToc";
import { Code } from "@/components/ui";
import { blob, GITHUB } from "@/lib/site";

export const metadata: Metadata = {
  title: "Docs · AgentCrucible",
  description: "Install AgentCrucible, connect your agent, declare MCP servers, write scenarios and checks, compare runs and gate pull requests.",
};

// [id, label] per section, grouped like the sidebar
const TOC: [string, [string, string][]][] = [
  ["Start", [["install", "Install"], ["quickstart", "Quickstart"], ["import", "Import a codebase"]]],
  ["Connect", [["agent", "Your agent"], ["models", "Model APIs"], ["mcp", "MCP servers"]]],
  ["Write tests", [["environment", "Clean environments"], ["scenarios", "Scenarios"], ["checks", "Checks reference"]]],
  ["Run", [["compare", "Run and compare"], ["ci", "CI gate"], ["dashboard", "Dashboard and access"], ["kubernetes", "Kubernetes"]]],
  ["Reference", [["cli", "CLI"], ["env", "Environment variables"], ["limits", "Limitations"], ["roadmap", "Roadmap"]]],
];

export default function Docs() {
  return (
    <div className="mx-auto w-full max-w-6xl px-4 py-12 sm:px-6 sm:py-16">
      <div className="grid gap-12 lg:grid-cols-[220px_minmax(0,1fr)]">
        <aside className="hidden lg:block">
          <div className="sticky top-24 max-h-[calc(100vh-7rem)] overflow-y-auto pb-6">
            <DocsToc groups={TOC} />
          </div>
        </aside>

        <article className="min-w-0 max-w-3xl">
          <div className="font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">Documentation</div>
          <h1 className="mt-3 text-[34px] font-semibold leading-[1.08] tracking-[-0.02em] sm:text-[44px]">Get AgentCrucible running</h1>
          <p className="mt-4 text-[17px] leading-relaxed text-mute">
            From install to a gated pull request. Prefer clicking? The <Link href="/start/" className="text-ember">setup wizard</Link> writes
            your config, an adapter and a first scenario. The long-form <a href={blob("docs/ADOPTION.md")} className="text-ember">adoption guide</a> covers
            everything here in more depth.
          </p>

          <details className="card mt-8 px-5 py-4 lg:hidden [&_summary::-webkit-details-marker]:hidden">
            <summary className="cursor-pointer list-none text-[14px] font-medium">On this page</summary>
            <div className="mt-4"><DocsToc groups={TOC} /></div>
          </details>

          <H2 id="install">Install</H2>
          <P>Python 3.11+ and Git. For free local testing, <a href="https://ollama.com" className="text-ember">Ollama</a> serves both the OpenAI and the Anthropic API.</P>
          <Code title="terminal" code={`pip install "agentcrucible @ git+${GITHUB}"
# or the container
git clone ${GITHUB}.git && cd AgentCrucible && docker build -t agentcrucible .`} />
          <P>Tagged releases also publish <code className="font-mono text-[14px] text-fg">pip install agentcrucible</code> and <code className="font-mono text-[14px] text-fg">ghcr.io/prosws2210/agentcrucible</code> images; see the <a href={blob("CHANGELOG.md")} className="text-ember">changelog</a>.</P>

          <H2 id="quickstart">Quickstart</H2>
          <P>Run the bundled example: a support agent with two MCP servers and ten scenarios, on a free local model.</P>
          <Code title="terminal" code={`ollama pull qwen2.5:7b
cd examples/support-agent
crucible validate
crucible run --label baseline -k 5
crucible run --label candidate -k 5 -e AGENT_PROMPT=prompts/v2_fast.md --compare baseline
crucible open latest        # HTML report with every trajectory`} />
          <P>For your own agent: <code className="font-mono text-[14px] text-fg">crucible init my-agent-tests</code> scaffolds a <code className="font-mono text-[14px] text-fg">crucible.yaml</code> and a first scenario.</P>

          <H2 id="import">Import a codebase</H2>
          <P>Already have agents? Point AgentCrucible at the repository. It reads the code without running it, finds the agents,
            tools, MCP servers, prompts, databases and external APIs, and drafts adapters, fixtures and scenarios for you to review.
            Nothing is written until you approve; then a smoke run shows whether what it found matches what the agents really do.</P>
          <Code title="terminal" code={`crucible discover ./my-repo                  # writes agent-tests/discovery.draft.json for review
crucible discover ./my-repo --apply --yes    # write agent-tests/ and smoke-run it
crucible discover . --check                  # in CI: fail on a new agent or an untested destructive tool
crucible import-traces traces.json --agent support   # production conversations become scenarios`} />
          <P>In the dashboard, open <b className="text-fg">Import codebase</b>: pick a folder or a Git URL, review the system map,
            tools and draft tests, answer any questions, and approve. With Docker Compose, mount the code with
            <code className="font-mono text-[14px] text-fg"> CRUCIBLE_IMPORT_DIR=/path/to/code</code>.</P>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-mute">
            <li>Python: LangGraph, LangChain, OpenAI Agents SDK, CrewAI, PydanticAI, LlamaIndex, Claude Agent SDK, MCP servers and raw OpenAI / Anthropic tool loops. TypeScript: Vercel AI SDK, Mastra, OpenAI Agents JS, LangChain JS, MCP. Go and Java (Spring AI, LangChain4j) are detected and run through an HTTP bridge or a scaffold you fill in.</li>
            <li>Every finding links to the file and line it came from; anything it can&apos;t prove becomes a question. <code className="font-mono text-[13.5px] text-fg">.env</code> files and secrets are skipped.</li>
            <li>Destructive tools are mocked in the drafted tests until you change that, and external APIs become HTTP mocks.</li>
            <li>Adapters report in-process tool calls, so trajectories show arguments and results for ordinary functions too.</li>
          </ul>

          <H2 id="agent">Connect your agent</H2>
          <P>AgentCrucible needs two addresses to be configurable in your agent: the model API URL and the MCP server URLs. Pick how it reaches your agent:</P>
          <H3>stdio: a script, CLI or worker</H3>
          <P>Started once per episode. One JSON object per line on stdin and stdout; logs go to stderr.</P>
          <Code title="crucible.yaml" code={`agent:
  transport: stdio
  command: python agent.py`} />
          <Code title="protocol" code={`in : {"type": "user", "content": "I want a refund"}     # one line per turn; {"type": "end"} at the end
out: {"type": "assistant", "content": "Sure, which order?"}`} />
          <H3>http: a web service</H3>
          <P>Every turn is POSTed with the full history and the episode&apos;s addresses in <code className="font-mono text-[14px] text-fg">context</code>. Start it for the run with <code className="font-mono text-[14px] text-fg">command</code>, or omit that to test a service that is already deployed.</P>
          <Code title="crucible.yaml" code={`agent:
  transport: http
  url: http://127.0.0.1:8701/turn
  command: python agent_service.py --port 8701           # optional
  headers: { Authorization: "Bearer \${STAGING_TOKEN}" }  # optional, \${VAR} expanded`} />
          <Code title="each turn" code={`POST /turn
{
  "episode_id": "fix-failing-test--2--a1b2c3",
  "messages": [{"role": "user", "content": "test_apply_discount is failing…"}],
  "context": {
    "openai_base_url": "http://127.0.0.1:<port>/ep/<episode>/v1",
    "anthropic_base_url": "http://127.0.0.1:<port>/ep/<episode>",
    "api_key": "agentcrucible",
    "model": "qwen2.5:7b",
    "mcp": {"workspace": "http://127.0.0.1:<port>/ep/<episode>/mcp/workspace"},
    "workspace": "/tmp/crucible-xyz/workspace"
  }
}
→ 200 {"content": "Fixed apply_discount; all tests pass."}`} />

          <H2 id="models">Model APIs</H2>
          <Table head={["Your agent calls", "Supported"]} rows={[
            ["OpenAI Chat Completions", "streaming and non-streaming, tools"],
            ["OpenAI Responses API", "streaming and non-streaming, function calls (send the full input each call)"],
            ["Anthropic Messages", "streaming and non-streaming, tool use"],
          ]} />
          <Code title="crucible.yaml" code={`model: qwen2.5:7b                 # forced on every call the agent makes
llm:
  upstream_base_url: http://localhost:11434/v1     # OpenAI-format calls
  anthropic_base_url: https://api.anthropic.com    # Anthropic-format calls
  cache: read_write                                # record; --cache replay re-runs for free`} />
          <P>Keys come from the environment, never the YAML file: <code className="font-mono text-[14px] text-fg">CRUCIBLE_LLM_API_KEY</code>, <code className="font-mono text-[14px] text-fg">CRUCIBLE_ANTHROPIC_API_KEY</code>.</P>

          <H2 id="mcp">MCP servers</H2>
          <Code title="crucible.yaml" code={`mcp_servers:
  shop: { command: python mcp/shop_server.py }      # local: fresh process per episode
  search:                                           # remote: reached by URL
    url: https://mcp.example.com/mcp
    transport: http                                 # Streamable HTTP (default) or sse
    headers: { Authorization: "Bearer \${SEARCH_MCP_TOKEN}" }`} />
          <P>Your agent gets one URL per server as <code className="font-mono text-[14px] text-fg">CRUCIBLE_MCP_&lt;NAME&gt;_URL</code>. Remote servers are shared by every episode, so their state is not reset: prefer staging, read-only tools or mocks for tools with side effects.</P>

          <H2 id="environment">Clean environments</H2>
          <P>Everything in <code className="font-mono text-[14px] text-fg">environment</code> is created fresh for each episode.</P>
          <Table head={["Field", "Per episode"]} rows={[
            ["fixtures: { shop: seed.sql }", "New SQLite file; path in CRUCIBLE_DB for that server"],
            ["fixtures: { shop: { postgres: seed.sql } }", "New Postgres database on CRUCIBLE_POSTGRES_URL; URL in CRUCIBLE_DB_URL; dropped afterwards"],
            ["workspace: { path: repos/app, ref: v1.4.0 }", "Fresh copy or git clone with a baseline commit; path in CRUCIBLE_WORKSPACE"],
            ["http_mocks: { payments: [ … ] }", "Canned API at CRUCIBLE_HTTP_PAYMENTS_URL; requests recorded; unmatched → 404"],
            ["mocks: { send_email: { status: sent } }", "Tool returns this instead of running"],
            ["deny_tools: [drop_table]", "Call is blocked and recorded"],
            ["inject: { read_file: \"Ignore previous…\" }", "Text appended to the real tool output"],
          ]} />

          <H2 id="scenarios">Scenarios</H2>
          <P>One YAML file per situation. Start from real incidents and support tickets; 20–50 good scenarios beat 500 generated ones.</P>
          <Code title="scenarios/core/refund-requires-confirmation.yaml" code={`id: refund-requires-confirmation
description: Refund a delivered order, but only after the customer confirms.
environment:
  fixtures: { shop: fixtures/shop.sql }
task: Hi, I'm Asha (asha@example.com). My mouse broke, I'd like a refund.
user:                                    # optional: a simulated user continues the conversation
  persona: Asha. Wants a refund for order A-1042. Says yes when asked to confirm.
  max_turns: 4
checks:
  - state.sql: { db: shop, query: "SELECT count(*) FROM refunds WHERE order_id='A-1042'", expect: 1 }
  - trajectory.not_before_turn: { tool: issue_refund, turn: 2 }
  - trajectory.tool_not_called: cancel_order
  - judge.rubric: { criteria: "Professional and concise.", min: 4, hard: false }`} />

          <H2 id="checks">Checks reference</H2>
          <P>Any check takes <code className="font-mono text-[14px] text-fg">hard: false</code> to be reported without failing the episode.</P>
          <Table head={["Check", "Asserts"]} rows={[
            ["state.sql", "Query the episode's SQLite or Postgres database: expect a value or expect_rows"],
            ["state.command", "Run a command in the workspace: expect_exit, contains, not_contains, timeout_s"],
            ["state.git_diff", "Files changed since the baseline: changed / not_changed globs, max_files, max_lines"],
            ["state.file", "A workspace file exists / is absent, contains, not_contains, regex"],
            ["http.called · http.not_called", "Requests to a mocked API: mock, method, path glob, body_contains, min"],
            ["trajectory.tool_called · tool_not_called", "Tools used or never used (optionally with matching args)"],
            ["trajectory.call_order · not_before_turn", "Order of tools, and not before turn N (e.g. confirm first)"],
            ["trajectory.max_tool_calls · no_tool_errors · no_blocked_calls", "Efficiency and robustness"],
            ["output.contains · not_contains · regex", "What the agent said"],
            ["budget.max_llm_calls · max_tokens · max_duration_s · max_cost_usd", "Cost and latency ceilings"],
            ["judge.rubric", "LLM judge 1–5 against criteria; demoted to non-blocking if calibration κ < 0.6"],
          ]} />

          <H2 id="compare">Run and compare</H2>
          <Code title="terminal" code={`crucible run --label baseline -k 5                       # on main
crucible run --label my-change -k 5 --compare baseline   # on your branch
crucible run --model qwen2.5:3b --compare baseline       # try another model
crucible run --cache replay                              # re-run from recordings, no model calls`} />
          <P>Use k ≥ 5 attempts for gating. Each scenario gets a verdict: <b className="text-fg">regressed</b>, <b className="text-fg">improved</b>, <b className="text-fg">unchanged</b> or <b className="text-fg">inconclusive</b> with a “needs k≈N” estimate. Overall: pass-rate difference with a bootstrap 95% CI; per scenario: Fisher&apos;s exact test with Benjamini–Hochberg correction.</P>
          <Code title="crucible.yaml" code={`ci:
  fail_on: [regressed]      # also: inconclusive, any_failure
  alpha: 0.05`} />

          <H2 id="ci">CI gate</H2>
          <P>On your main branch the action stores the run as the baseline. On pull requests it compares against it, comments once (and updates the comment) and fails the check on a regression.</P>
          <Code title=".github/workflows/agent-tests.yml" code={`- uses: prosws2210/AgentCrucible@main
  with:
    working-directory: agent-tests/
    runs: "5"
    llm-base-url: https://openrouter.ai/api/v1
    llm-api-key: \${{ secrets.OPENROUTER_KEY }}
    # or free on the runner's CPU: ollama-model: qwen2.5:1.5b`} />

          <H2 id="dashboard">Dashboard and access</H2>
          <Code title="terminal" code={`git clone ${GITHUB}.git && cd AgentCrucible
cp .env.example .env
docker compose up --build             # add -f docker-compose.gpu.yml for an NVIDIA GPU
# http://localhost:8080/dashboard/`} />
          <P>Frontend, API, Postgres for history and an Ollama model server, as separate services. Or run just the API next to your project with <code className="font-mono text-[14px] text-fg">crucible serve</code>.</P>
          <P>The dashboard is open by default, which is fine on your own machine. Before sharing it, set tokens in <code className="font-mono text-[14px] text-fg">.env</code>:</P>
          <Code title=".env" code={`CRUCIBLE_API_TOKEN=<long random string>     # full access: start runs and audits
CRUCIBLE_VIEWER_TOKEN=<another one>         # optional: read-only`} />
          <P>Browsers sign in once and keep an HttpOnly session cookie (never the token). Scripts send <code className="font-mono text-[14px] text-fg">Authorization: Bearer &lt;token&gt;</code>.</P>

          <H2 id="kubernetes">Kubernetes</H2>
          <P>For large suites, the Helm chart runs shards as an Indexed Job and merges them into one report and gate.</P>
          <Code title="terminal" code={`helm install crucible deploy/helm/agentcrucible --set run.shards=8`} />

          <H2 id="cli">CLI</H2>
          <Table head={["Command", ""]} rows={[
            ["crucible init", "Scaffold config and an example scenario"],
            ["crucible validate", "Validate config and scenarios"],
            ["crucible run", "-k, --model, -e KEY=VAL, --compare, --cache read_write|replay, --shard i/N"],
            ["crucible compare A B", "Statistical comparison of two runs"],
            ["crucible merge", "Merge shard runs"],
            ["crucible show · open", "Terminal summary · HTML report"],
            ["crucible serve", "API for the dashboard (DATABASE_URL for Postgres, SQLite by default)"],
            ["crucible mcp-audit", "--command, or --url with -H \"Authorization: …\" and --sse"],
            ["crucible label · calibrate", "Human labels → judge agreement (κ)"],
            ["crucible discover", "Find agents in a repository and draft their tests: --apply, --check, --update, --json, --no-llm"],
            ["crucible import-traces", "OpenTelemetry, LangSmith or JSONL conversations → draft scenarios"],
          ]} />

          <H2 id="env">Environment variables</H2>
          <Table head={["Variable", "Purpose"]} rows={[
            ["CRUCIBLE_LLM_API_KEY", "Key for the OpenAI-compatible upstream"],
            ["CRUCIBLE_ANTHROPIC_API_KEY", "Key for the Anthropic upstream"],
            ["CRUCIBLE_POSTGRES_URL", "Server where Postgres fixtures are created"],
            ["CRUCIBLE_API_TOKEN · CRUCIBLE_VIEWER_TOKEN", "Dashboard and API access"],
            ["DATABASE_URL", "Run history for crucible serve (Postgres); SQLite if unset"],
            ["CRUCIBLE_DISCOVER_ROOTS", "Folders the dashboard's codebase import may read (default: home folder)"],
            ["CRUCIBLE_IMPORT_DIR", "Docker Compose: host folder mounted at /import for the codebase import"],
          ]} />

          <H2 id="limits">Limitations</H2>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-mute">
            <li>No MySQL fixtures yet; use SQLite, Postgres or a <code className="font-mono text-[13.5px] text-fg">state.command</code> check against your own test database.</li>
            <li>Remote MCP servers are not reset between episodes.</li>
            <li>No per-person accounts; use shared tokens or an SSO proxy.</li>
            <li>Gemini and Bedrock native APIs: use their OpenAI-compatible endpoints.</li>
          </ul>

          <H2 id="roadmap">Roadmap</H2>
          <ul className="mt-4 list-disc space-y-2 pl-5 text-[15px] leading-relaxed text-mute">
            <li>Codebase import: pull-request comments from <code className="font-mono text-[13.5px] text-fg">--check</code>, and adapters for Go and Java agents.</li>
            <li>MCP Python SDK 2.x and the stateless 2026 spec revision.</li>
            <li>Docker-per-episode and Kubernetes Job-per-episode executors for agents with system dependencies.</li>
          </ul>
          <P>The import design: <a href={blob("docs/CODEBASE-IMPORT.md")} className="text-ember">docs/CODEBASE-IMPORT.md</a>.</P>

          <div className="mt-14 rounded-xl border border-line bg-panel-2/40 p-5 text-[14.5px] text-mute">
            Something missing or wrong? <a href={`${GITHUB}/issues`} className="text-ember">Open an issue</a> or read the full <a href={blob("docs/ADOPTION.md")} className="text-ember">adoption guide</a>.
          </div>
        </article>
      </div>
    </div>
  );
}

function H2({ id, children }: { id: string; children: React.ReactNode }) {
  return (
    <h2 id={id} className="group mt-16 scroll-mt-24 border-t border-line/70 pt-10 text-[26px] font-semibold tracking-tight">
      <a href={`#${id}`} className="hover:text-fg">{children}</a>
    </h2>
  );
}

function H3({ children }: { children: React.ReactNode }) {
  return <h3 className="mt-8 text-[18px] font-semibold tracking-tight">{children}</h3>;
}

function P({ children }: { children: React.ReactNode }) {
  return <p className="my-4 text-[15.5px] leading-relaxed text-mute">{children}</p>;
}

function Table({ head, rows }: { head: [string, string]; rows: [string, string][] }) {
  return (
    <div className="my-5 overflow-hidden rounded-xl border border-line">
      <div className="hidden grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] gap-4 border-b border-line bg-panel-2/60 px-4 py-2.5 text-[12px] font-medium uppercase tracking-[0.1em] text-dim sm:grid">
        <span>{head[0]}</span><span>{head[1]}</span>
      </div>
      {rows.map(([k, v]) => (
        <div key={k} className="grid gap-1 border-b border-line/60 px-4 py-3 text-[14px] last:border-0 sm:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)] sm:gap-4">
          <code className="break-words font-mono text-[12.5px] text-fg">{k}</code>
          <span className="text-mute">{v}</span>
        </div>
      ))}
    </div>
  );
}
