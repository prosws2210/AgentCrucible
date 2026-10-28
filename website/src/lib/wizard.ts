// Generates a starter project (crucible.yaml, agent adapter, first scenario, commands) from wizard answers.

export type AgentKind = "python" | "node" | "http";
export type LlmApi = "openai" | "anthropic";
export type Provider = "ollama" | "openai" | "anthropic" | "openrouter" | "custom";
export type StateKind = "none" | "sqlite" | "repo";

export type Answers = {
  project: string;
  agent: AgentKind;
  api: LlmApi;
  provider: Provider;
  model: string;
  customUrl: string;
  servers: { name: string; command: string }[];
  state: StateKind;
  task: string;
  mustCall: string;
  mustNotCall: string;
  replyMentions: string;
};

export const PROVIDERS: Record<Provider, { label: string; note: string; openai: string; anthropic: string; model: Record<LlmApi, string>; key?: string }> = {
  ollama: { label: "Ollama (free, local)", note: "Serves both the OpenAI and the Anthropic API on your machine.", openai: "http://localhost:11434/v1", anthropic: "http://localhost:11434", model: { openai: "qwen2.5:7b", anthropic: "qwen2.5:7b" } },
  openai: { label: "OpenAI", note: "Set CRUCIBLE_LLM_API_KEY.", openai: "https://api.openai.com/v1", anthropic: "", model: { openai: "gpt-4.1-mini", anthropic: "gpt-4.1-mini" }, key: "CRUCIBLE_LLM_API_KEY" },
  // The user simulator and judge speak the OpenAI format, so they use Anthropic's OpenAI-compatible endpoint.
  anthropic: { label: "Anthropic", note: "Set CRUCIBLE_ANTHROPIC_API_KEY and CRUCIBLE_LLM_API_KEY to your Anthropic key.", openai: "https://api.anthropic.com/v1", anthropic: "https://api.anthropic.com", model: { openai: "claude-sonnet-4-5", anthropic: "claude-sonnet-4-5" }, key: "CRUCIBLE_ANTHROPIC_API_KEY and CRUCIBLE_LLM_API_KEY" },
  openrouter: { label: "OpenRouter", note: "One key, many models. Set CRUCIBLE_LLM_API_KEY.", openai: "https://openrouter.ai/api/v1", anthropic: "", model: { openai: "openai/gpt-4.1-mini", anthropic: "anthropic/claude-sonnet-4.5" }, key: "CRUCIBLE_LLM_API_KEY" },
  custom: { label: "Other OpenAI-compatible URL", note: "vLLM, LiteLLM, Azure-compatible proxies, Groq…", openai: "", anthropic: "", model: { openai: "your-model", anthropic: "your-model" }, key: "CRUCIBLE_LLM_API_KEY" },
};

export const DEFAULTS: Answers = {
  project: "my-agent",
  agent: "python",
  api: "openai",
  provider: "ollama",
  model: "qwen2.5:7b",
  customUrl: "http://localhost:8000/v1",
  servers: [{ name: "tools", command: "python mcp/server.py" }],
  state: "none",
  task: "I'd like to cancel my last order.",
  mustCall: "",
  mustNotCall: "",
  replyMentions: "",
};

const slug = (s: string) => s.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "my-agent";
const yamlStr = (s: string) => (/^[\w./:@-]+$/.test(s) ? s : JSON.stringify(s));

export function crucibleYaml(a: Answers): string {
  const p = PROVIDERS[a.provider];
  const openaiUrl = a.provider === "custom" ? a.customUrl : p.openai;
  const agent = a.agent === "http"
    ? `agent:
  transport: http
  url: http://127.0.0.1:8701/turn
  # started once per run; remove "command" to test a service that is already running
  command: python agent_service.py --port 8701
  turn_timeout_s: 300`
    : `agent:
  transport: stdio
  command: ${a.agent === "node" ? "node agent.mjs" : "python agent.py"}   # started once per episode
  turn_timeout_s: 300`;

  const llm = [`  upstream_base_url: ${openaiUrl || "http://localhost:11434/v1"}`];
  if (a.api === "anthropic") llm.push(`  anthropic_base_url: ${p.anthropic || "https://api.anthropic.com"}`);
  llm.push(`  # read_write records responses; \`crucible run --cache replay\` re-runs for free`);
  llm.push(`  cache: read_write`);

  const servers = a.servers.filter((s) => s.name.trim() && s.command.trim());
  const mcp = servers.length
    ? `mcp_servers:\n${servers.map((s) => {
        const v = s.command.trim();
        // a URL means an already-running remote server (Streamable HTTP); anything else is a stdio command
        return `  ${slug(s.name).replace(/-/g, "_")}: { ${isUrl(v) ? "url" : "command"}: ${yamlStr(v)} }`;
      }).join("\n")}${servers.some((s) => isUrl(s.command.trim())) ? '\n  # remote server needs auth? add  headers: { Authorization: "Bearer ${MCP_TOKEN}" }' : ""}`
    : "mcp_servers: {}";

  return `version: 1
project: ${slug(a.project)}

${agent}

model: ${a.model}      # forced on every LLM call your agent makes
llm:
${llm.join("\n")}
${p.key ? `# API keys come from the environment (${p.key}), never from this file\n` : ""}
${mcp}

# the simulator plays the user in multi-turn scenarios; the judge scores rubrics
simulator: { model: ${a.model} }
judge:     { model: ${a.model}, temperature: 0 }

suites:
  smoke: { path: scenarios/smoke, runs: 3 }

ci:
  fail_on: [regressed]
`;
}

export function scenarioYaml(a: Answers): string {
  const servers = a.servers.filter((s) => s.name.trim());
  const first = servers[0] ? slug(servers[0].name).replace(/-/g, "_") : "tools";
  const env: string[] = [];
  if (a.state === "sqlite") env.push(`  # fresh SQLite database per episode, path in CRUCIBLE_DB
  fixtures: { ${first}: fixtures/seed.sql }`);
  if (a.state === "repo") env.push(`  # fresh copy of the repo per episode, path in CRUCIBLE_WORKSPACE
  workspace: { path: repos/my-repo }`);
  const checks: string[] = [];
  if (a.mustCall.trim()) checks.push(`  - trajectory.tool_called: ${a.mustCall.trim()}`);
  if (a.mustNotCall.trim()) checks.push(`  - trajectory.tool_not_called: ${a.mustNotCall.trim()}`);
  if (a.replyMentions.trim()) checks.push(`  - output.contains: ${yamlStr(a.replyMentions.trim())}`);
  if (a.state === "repo") {
    checks.push(`  # the tests must pass, without the agent editing them`);
    checks.push(`  - state.command: { run: python -m pytest, expect_exit: 0 }`);
    checks.push(`  - state.git_diff: { not_changed: "tests/**" }`);
  }
  if (a.state === "sqlite") checks.push(`  - state.sql:
      db: ${first}
      query: SELECT count(*) FROM orders WHERE status = 'cancelled'
      expect: 1`);
  checks.push(`  - trajectory.max_tool_calls: 10`);
  checks.push(`  - judge.rubric: { criteria: "Helpful, correct and professional.", min: 4, hard: false }`);

  return `id: first-scenario
description: Replace with a real situation your agent must handle.
${env.length ? `environment:\n${env.join("\n")}\n` : ""}task: ${JSON.stringify(a.task || "Hello!")}
# optional: an LLM keeps the conversation going as this persona
user:
  persona: A customer who answers follow-up questions briefly and confirms when asked.
  max_turns: 4
checks:
${checks.join("\n")}
`;
}

export function adapterFile(a: Answers): { name: string; code: string; note: string } {
  const openaiClient = `client = OpenAI()  # reads OPENAI_BASE_URL and OPENAI_API_KEY from the environment`;
  const anthropicClient = `client = Anthropic()  # reads ANTHROPIC_BASE_URL and ANTHROPIC_API_KEY from the environment`;

  if (a.agent === "python") {
    return {
      name: "agent.py",
      note: "A thin wrapper around your existing agent. AgentCrucible starts it once per episode.",
      code: `"""Adapter between AgentCrucible and your agent (stdio, one JSON object per line)."""
import json, os, sys
${a.api === "anthropic" ? "from anthropic import Anthropic" : "from openai import OpenAI"}

# 1. Model calls: the SDK picks up the gateway address from the environment automatically.
${a.api === "anthropic" ? anthropicClient : openaiClient}
MODEL = os.environ.get("CRUCIBLE_MODEL", "${a.model}")

# 2. MCP servers: one URL per server in crucible.yaml (Streamable HTTP).
MCP_URLS = {k[len("CRUCIBLE_MCP_"):-len("_URL")].lower(): v
            for k, v in os.environ.items() if k.startswith("CRUCIBLE_MCP_") and k.endswith("_URL")}

def run_agent(history: list[dict]) -> str:
    """Call YOUR agent here with the conversation so far; return its reply."""
    raise NotImplementedError("plug in your agent: e.g. return my_agent.respond(history, client, MCP_URLS)")

history = []
for line in sys.stdin:                      # 3. one user turn per line
    msg = json.loads(line)
    if msg.get("type") == "end":
        break
    history.append({"role": "user", "content": msg["content"]})
    reply = run_agent(history)
    history.append({"role": "assistant", "content": reply})
    print(json.dumps({"type": "assistant", "content": reply}), flush=True)   # logs go to stderr
`,
    };
  }
  if (a.agent === "node") {
    return {
      name: "agent.mjs",
      note: "A thin wrapper around your existing agent. AgentCrucible starts it once per episode.",
      code: `// Adapter between AgentCrucible and your agent (stdio, one JSON object per line).
import readline from "node:readline";
${a.api === "anthropic" ? `import Anthropic from "@anthropic-ai/sdk";\nconst client = new Anthropic(); // reads ANTHROPIC_BASE_URL / ANTHROPIC_API_KEY` : `import OpenAI from "openai";\nconst client = new OpenAI(); // reads OPENAI_BASE_URL / OPENAI_API_KEY`}
const MODEL = process.env.CRUCIBLE_MODEL ?? "${a.model}";

// MCP servers: one Streamable HTTP URL per server in crucible.yaml
const MCP_URLS = Object.fromEntries(Object.entries(process.env)
  .filter(([k]) => k.startsWith("CRUCIBLE_MCP_") && k.endsWith("_URL"))
  .map(([k, v]) => [k.slice(13, -4).toLowerCase(), v]));

async function runAgent(history) {
  // Call YOUR agent here with the conversation so far; return its reply.
  throw new Error("plug in your agent");
}

const history = [];
for await (const line of readline.createInterface({ input: process.stdin })) {
  const msg = JSON.parse(line);
  if (msg.type === "end") break;
  history.push({ role: "user", content: msg.content });
  const reply = await runAgent(history);
  history.push({ role: "assistant", content: reply });
  process.stdout.write(JSON.stringify({ type: "assistant", content: reply }) + "\\n"); // logs -> stderr
}
`,
    };
  }
  return {
    name: "agent_service.py",
    note: "Your agent as an HTTP endpoint. Every turn arrives with the episode's gateway addresses in `context`.",
    code: `"""Your agent as an HTTP service (any framework works; FastAPI shown)."""
from fastapi import FastAPI
${a.api === "anthropic" ? "from anthropic import AsyncAnthropic" : "from openai import AsyncOpenAI"}

app = FastAPI()

@app.post("/turn")
async def turn(body: dict) -> dict:
    ctx = body["context"]          # set by AgentCrucible for this episode
    ${a.api === "anthropic"
      ? `client = AsyncAnthropic(base_url=ctx["anthropic_base_url"], api_key=ctx["api_key"])`
      : `client = AsyncOpenAI(base_url=ctx["openai_base_url"], api_key=ctx["api_key"])`}
    mcp_urls = ctx["mcp"]          # {server_name: streamable-http URL}
    model = ctx["model"]
    history = body["messages"]     # [{"role": "user" | "assistant", "content": "..."}]

    reply = await my_agent(history, client, mcp_urls, model)   # <- your agent
    return {"content": reply}

if __name__ == "__main__":
    import argparse, uvicorn
    p = argparse.ArgumentParser(); p.add_argument("--port", type=int, default=8701)
    uvicorn.run(app, host="127.0.0.1", port=p.parse_args().port)
`,
  };
}

export function commands(a: Answers): string {
  const p = PROVIDERS[a.provider];
  const lines = [
    "# 1. install",
    `pip install "agentcrucible[examples] @ git+https://github.com/prosws2210/AgentCrucible"`,
  ];
  if (a.provider === "ollama") lines.push(`ollama pull ${a.model}`);
  if (p.key) p.key.split(" and ").forEach((k) => lines.push(`export ${k}=...   # your key`));
  lines.push(
    "",
    "# 2. check the files, then run the first scenario",
    "crucible validate",
    "crucible run --label baseline",
    "",
    "# 3. see results in the dashboard (or: docker compose up for the full stack)",
    "crucible serve --port 8000",
  );
  return lines.join("\n");
}

export const isUrl = (v: string) => /^https?:\/\//i.test(v);
