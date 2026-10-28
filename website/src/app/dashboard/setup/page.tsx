"use client";

import { PageHeader, useProject } from "@/components/app/AppShell";
import { useResource } from "@/components/app/hooks";
import { IconCheck, IconRefresh, IconX } from "@/components/Icons";
import { Badge, Button, Card, CardHeader, Code, Spinner } from "@/components/ui";
import type { AuthStatus, Config, Doctor } from "@/lib/api";
import { GITHUB } from "@/lib/site";

const FIX: Record<string, string> = {
  model: "Start your model server (e.g. `ollama serve` and `ollama pull <model>`), or point `llm.upstream_base_url` in crucible.yaml at your provider. Keys go in CRUCIBLE_LLM_API_KEY / CRUCIBLE_ANTHROPIC_API_KEY.",
  agent: "Check `agent.command` (stdio) or `agent.url` (http) in crucible.yaml. Paths are relative to the folder that holds crucible.yaml.",
  config: "Add scenario YAML files under the paths listed in `suites`.",
  mcp: "Local server: run its command by hand in the project folder to see the error; it must speak MCP over stdio. Remote server: check the URL, that it serves Streamable HTTP (or set `transport: sse`), and its `headers`.",
};

export default function SetupPage() {
  const doctor = useResource<Doctor>("/api/doctor");
  const cfg = useResource<Config>("/api/config");
  const auth = useResource<AuthStatus>("/api/auth/status");
  const { canWrite } = useProject();
  const c = cfg.data;

  return (
    <>
      <PageHeader
        title="Setup"
        sub="Everything a run needs: your agent, a model endpoint and your MCP servers. Configuration lives in crucible.yaml next to your scenarios."
        actions={<Button variant="secondary" href="/start/">Connect a different agent</Button>}
      />

      <Card>
        <CardHeader
          title="Connection check"
          sub="Starts each local MCP server once, connects to remote ones, and asks the model server for its models."
          action={<Button variant="secondary" onClick={doctor.reload}><IconRefresh className="h-3.5 w-3.5" /> Re-check</Button>}
        />
        {!doctor.data ? (
          <div className="flex items-center gap-2 px-5 py-8 text-[13px] text-dim"><Spinner /> Checking…</div>
        ) : (
          <ul className="divide-y divide-line/70">
            {doctor.data.checks.map((ch) => (
              <li key={ch.id} className="flex items-start gap-3 px-5 py-3.5">
                <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${ch.ok ? "bg-ok/15 text-ok" : "bg-bad/15 text-bad"}`}>
                  {ch.ok ? <IconCheck className="h-3.5 w-3.5" /> : <IconX className="h-3.5 w-3.5" />}
                </span>
                <div className="min-w-0">
                  <div className="text-[13.5px] font-medium">{ch.label}</div>
                  <div className="break-words text-[12.5px] text-mute">{ch.detail}</div>
                  {!ch.ok && <div className="mt-1.5 text-[12.5px] text-warn">How to fix: {FIX[ch.id.split(":")[0]] ?? "See the adoption guide."}</div>}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <div className="mt-5 grid gap-5 lg:grid-cols-2">
        <Card>
          <CardHeader title="Your agent" sub={c?.agent.transport === "http" ? "An HTTP service: every turn is POSTed with the gateway addresses." : "A process started for every episode; it talks JSON lines over stdin/stdout."} />
          {c ? (
            <dl className="divide-y divide-line/70 text-[13px]">
              <Row k="Transport"><Badge tone="ember">{c.agent.transport}</Badge></Row>
              {c.agent.command && <Row k="Command"><code className="font-mono text-[12px]">{c.agent.command}</code></Row>}
              {c.agent.url && <Row k="URL"><code className="font-mono text-[12px]">{c.agent.url}</code></Row>}
              <Row k="Turn timeout">{c.agent.turn_timeout_s}s</Row>
            </dl>
          ) : <Loading />}
        </Card>

        <Card>
          <CardHeader title="Models" sub="Your agent's LLM calls go through AgentCrucible's gateway to this endpoint." />
          {c ? (
            <dl className="divide-y divide-line/70 text-[13px]">
              <Row k="Model under test"><code className="font-mono text-[12px]">{c.model}</code></Row>
              <Row k="OpenAI-format"><code className="break-all font-mono text-[12px]">{c.llm.openai_base_url}</code></Row>
              <Row k="Anthropic-format"><code className="break-all font-mono text-[12px]">{c.llm.anthropic_base_url}</code></Row>
              <Row k="User simulator">{c.simulator_model}</Row>
              <Row k="Judge">{c.judge_model}</Row>
              <Row k="Response cache">{c.llm.cache}</Row>
            </dl>
          ) : <Loading />}
        </Card>

        <Card>
          <CardHeader title="MCP servers" sub="Local servers start fresh for every episode, with their own database. Remote servers are shared, so tests see their real state." />
          {c ? (
            c.mcp_servers.length === 0 ? <div className="px-5 py-6 text-[13px] text-dim">None configured.</div> : (
              <dl className="divide-y divide-line/70 text-[13px]">
                {c.mcp_servers.map((s) => (
                  <Row key={s.name} k={s.name}>
                    <Badge tone={s.remote ? "info" : "mute"} className="mr-2">{s.remote ? "remote" : "local"}</Badge>
                    <code className="break-all font-mono text-[12px]">{s.url ?? s.command}</code>
                  </Row>
                ))}
              </dl>
            )
          ) : <Loading />}
        </Card>

        <Card>
          <CardHeader title="Access" sub="Who can use this dashboard and API." />
          {auth.data ? (
            auth.data.required ? (
              <dl className="divide-y divide-line/70 text-[13px]">
                <Row k="Protection"><Badge tone="ok">token required</Badge></Row>
                <Row k="You">{canWrite ? "full access" : "read-only"}</Row>
              </dl>
            ) : (
              <div className="space-y-3 p-5 text-[13px] text-mute">
                <p><Badge tone="warn">open</Badge> Anyone who can reach this server can start runs. Fine on your laptop; set a token before sharing it.</p>
                <Code title=".env" code={"CRUCIBLE_API_TOKEN=<long random string>     # full access\nCRUCIBLE_VIEWER_TOKEN=<another one>         # optional, read-only"} />
              </div>
            )
          ) : <Loading />}
        </Card>

        <Card>
          <CardHeader title="Test suites" sub="Folders of scenario files and how many attempts each gets by default." />
          {c ? (
            <dl className="divide-y divide-line/70 text-[13px]">
              {Object.entries(c.suites).map(([n, s]) => (
                <Row key={n} k={n}><code className="font-mono text-[12px]">{s.path}</code> <span className="text-dim">· {s.runs}× by default</span></Row>
              ))}
              <Row k="Gate fails on">{c.gate.fail_on.join(", ")} <span className="text-dim">· α = {c.gate.alpha}</span></Row>
            </dl>
          ) : <Loading />}
        </Card>

        <Card>
          <CardHeader title="Gate pull requests in CI" sub="Same engine as this dashboard, as a GitHub Action." />
          <div className="p-5">
            <Code title=".github/workflows/agent-tests.yml" code={`- uses: prosws2210/AgentCrucible@main\n  with:\n    working-directory: .   # folder with crucible.yaml\n    runs: "5"\n    llm-base-url: https://openrouter.ai/api/v1\n    llm-api-key: \${{ secrets.LLM_API_KEY }}`} />
            <a href={`${GITHUB}/blob/main/docs/ADOPTION.md#5-baseline-and-ci`} target="_blank" rel="noreferrer" className="mt-3 inline-block text-[13px] text-ember">CI guide →</a>
          </div>
        </Card>
      </div>
    </>
  );
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-3 px-5 py-3">
      <dt className="text-mute">{k}</dt>
      <dd className="min-w-0 text-right">{children}</dd>
    </div>
  );
}

function Loading() {
  return <div className="flex items-center gap-2 px-5 py-6 text-[13px] text-dim"><Spinner /> Loading…</div>;
}
