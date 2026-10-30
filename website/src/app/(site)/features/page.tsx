import type { Metadata } from "next";
import { IconBolt, IconCheck, IconCode, IconGit, IconOverview, IconRefresh, IconRuns, IconScenarios, IconServer, IconSetup, IconShield } from "@/components/Icons";
import { ProductPreview } from "@/components/ProductPreview";
import { Cta, CtaBand, Heading, More, PageHero, Section, Serif } from "@/components/site/kit";
import { Code } from "@/components/ui";

export const metadata: Metadata = {
  title: "Features · AgentCrucible",
  description: "A local dashboard, a CLI, a pull-request gate, MCP server audits, calibrated LLM judges, a replay cache, access control and Kubernetes sharding.",
};

const DASHBOARD = [
  { icon: IconOverview, t: "Overview", b: "Pass rate over time, the latest verdict, and the scenarios that need attention." },
  { icon: IconRuns, t: "Runs", b: "Start a run with a model, prompt or env change, watch it live, compare with any baseline." },
  { icon: IconScenarios, t: "Scenarios", b: "Every test in plain words: what the user says, what must happen, how it did last time." },
  { icon: IconServer, t: "MCP servers", b: "Audit each server in one click and read the graded findings." },
  { icon: IconSetup, t: "Setup", b: "A connection check for the model, every MCP server and the agent, with fixes." },
  { icon: IconShield, t: "Sign-in", b: "Full-access and read-only tokens; the API needs one too." },
];

export default function Features() {
  return (
    <>
      <PageHero eyebrow="Features" toc={[["dashboard", "Dashboard"], ["cli", "CLI"], ["ci", "Pull-request gate"], ["more", "Audits, judges, replay…"], ["integrations", "Integrations"]]} title={<>Everything you need to <Serif>trust</Serif> an agent change</>}
        lead="A dashboard for the team, a CLI for your terminal, a gate for your pull requests and an audit for your tool servers. All self-hosted, all source-available.">
        <Cta href="/start/" primary>Get started free</Cta>
        <Cta href="/demo/">See a real run</Cta>
      </PageHero>

      <Section id="dashboard">
        <div className="grid items-center gap-10 lg:grid-cols-[0.9fr_1.1fr]">
          <Heading eyebrow="Dashboard" title={<>Your agent&apos;s test results, <Serif>in one place</Serif></>} className="mb-0"
            lead="One docker compose command starts the dashboard, the API, Postgres for history and a local model server. Nothing leaves your machine." />
          <ProductPreview />
        </div>
        <div className="mt-10 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {DASHBOARD.map(({ icon: Icon, t, b }) => (
            <div key={t} className="card p-5">
              <Icon className="h-5 w-5 text-ember" />
              <div className="mt-3 text-[15px] font-semibold">{t}</div>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-mute">{b}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section id="cli" className="border-t border-line/60">
        <div className="grid gap-10 lg:grid-cols-2">
          <div>
            <Heading eyebrow="CLI" title={<>Everything from <Serif>the terminal</Serif></>} className="mb-6"
              lead="The dashboard and CI use the same engine. Run a suite, compare two runs, open the report, audit a server or calibrate a judge." />
            <ul className="space-y-2.5 text-[14.5px] text-mute">
              {[
                ["crucible run", "suites, -k attempts, --model, -e KEY=VAL, --compare, --cache"],
                ["crucible compare A B", "statistical comparison of two runs"],
                ["crucible open latest", "self-contained HTML report"],
                ["crucible mcp-audit", "grade an MCP server, local or remote"],
                ["crucible label · calibrate", "measure how much to trust the judge"],
                ["crucible serve", "the API behind the dashboard"],
              ].map(([c, d]) => (
                <li key={c} className="flex flex-wrap gap-x-3"><code className="font-mono text-[13px] text-fg">{c}</code><span>{d}</span></li>
              ))}
            </ul>
          </div>
          <Code title="terminal" code={`$ crucible run --label new-prompt -k 5 \\
    -e AGENT_PROMPT=prompts/v2.md --compare baseline

pass@1 48% · pass^5 40% · Δ −30.0 pts (95% CI −56.0…−6.0)
GATE FAILED: overall pass rate significantly regressed

$ crucible open latest`} />
        </div>
      </Section>

      <Section id="ci" className="border-t border-line/60">
        <div className="grid gap-10 lg:grid-cols-2">
          <Code title=".github/workflows/agent-tests.yml" code={`on: pull_request
jobs:
  agent-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: prosws2210/AgentCrucible@main
        with:
          working-directory: tests/agent   # folder with crucible.yaml
          runs: "5"
          llm-base-url: https://openrouter.ai/api/v1
          llm-api-key: \${{ secrets.LLM_API_KEY }}`} />
          <div>
            <Heading eyebrow="Pull-request gate" title={<>Regressions <Serif>fail the build</Serif></>} className="mb-6"
              lead="The GitHub Action runs the suite on the pull request, compares it with the baseline from your main branch, comments the verdict and fails the check on a significant regression." />
            <ul className="space-y-2.5 text-[14.5px]">
              <Li>Choose what fails the gate: regressions, or also inconclusive results</Li>
              <Li>Free on the runner&apos;s CPU with a small Ollama model, or any hosted API</Li>
              <Li>Recorded responses make re-runs cheap; <code className="font-mono text-[13px]">--cache replay</code> costs nothing</Li>
            </ul>
          </div>
        </div>
      </Section>

      <Section id="more" className="border-t border-line/60">
        <Heading eyebrow="And" title={<>The details that make it <Serif>trustworthy</Serif></>} />
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Feature icon={IconServer} t="MCP server audit" b="Conformance, tool-description quality, fuzzing, SQL injection / path traversal / SSRF probes, a model-in-the-loop tool-choice test and latency. A critical finding caps the grade at D." />
          <Feature icon={IconCheck} t="Calibrated LLM judges" b="Label episodes yourself; Cohen's κ decides whether the judge may fail the build (κ ≥ 0.6), only advise, or is disabled." />
          <Feature icon={IconRefresh} t="Record & replay" b="Every model response is cached by request. Replay a whole suite without a model, to debug a check or re-grade old runs." />
          <Feature icon={IconBolt} t="Model swaps at the gateway" b="Force any model for every call, so the same suite compares models fairly, with tokens and latency per episode." />
          <Feature icon={IconShield} t="Access control" b="CRUCIBLE_API_TOKEN for full access, CRUCIBLE_VIEWER_TOKEN for read-only. Session cookies are HttpOnly and never hold the token." />
          <Feature icon={IconGit} t="Kubernetes sharding" b="The Helm chart splits large suites across an Indexed Job and merges the shards into one report and one gate." />
        </div>
      </Section>

      <Section id="integrations" className="border-t border-line/60">
        <Heading eyebrow="Integrations" title={<>Works with <Serif>what you already have</Serif></>}
          lead="No SDK to install in your agent. If it calls a model API and MCP servers, it works." />
        <div className="grid gap-4 md:grid-cols-2">
          <Matrix title="Your agent" items={[["stdio process", "one process per episode, JSON lines"], ["HTTP service", "started for the run, or already deployed (with auth headers)"], ["Any language", "Python, Node.js, Go… anything that reads env vars"]]} />
          <Matrix title="Model APIs" items={[["OpenAI Chat Completions", "streaming and non-streaming"], ["OpenAI Responses API", "streaming and non-streaming"], ["Anthropic Messages", "streaming, tool use"], ["Providers", "Ollama, vLLM, OpenAI, Anthropic, OpenRouter, Groq…"]]} />
          <Matrix title="MCP servers" items={[["Local (stdio)", "started fresh per episode"], ["Remote (Streamable HTTP or SSE)", "by URL, with ${ENV}-expanded headers"]]} />
          <Matrix title="Test environments" items={[["SQLite and Postgres", "a fresh database per episode"], ["Git repositories and folders", "a fresh copy per episode"], ["HTTP APIs", "mocked, every request recorded"]]} />
        </div>
        <div className="mt-8"><More href="/docs/">Read the documentation</More></div>
      </Section>

      <CtaBand />
    </>
  );
}

function Li({ children }: { children: React.ReactNode }) {
  return <li className="flex gap-3"><IconCheck className="mt-1 h-4 w-4 shrink-0 text-ok" /><span>{children}</span></li>;
}

function Feature({ icon: Icon, t, b }: { icon: typeof IconCode; t: string; b: string }) {
  return (
    <div className="card p-6">
      <Icon className="h-5 w-5 text-ember" />
      <div className="mt-3 text-[16px] font-semibold">{t}</div>
      <p className="mt-2 text-[14px] leading-relaxed text-mute">{b}</p>
    </div>
  );
}

function Matrix({ title, items }: { title: string; items: [string, string][] }) {
  return (
    <div className="card overflow-hidden">
      <div className="border-b border-line bg-panel-2/60 px-5 py-3 text-[14px] font-semibold">{title}</div>
      <ul className="divide-y divide-line/60">
        {items.map(([k, v]) => (
          <li key={k} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-5 py-3 text-[14px]">
            <span className="flex items-center gap-2 font-medium"><IconCheck className="h-3.5 w-3.5 text-ok" />{k}</span>
            <span className="text-[13px] text-mute">{v}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
