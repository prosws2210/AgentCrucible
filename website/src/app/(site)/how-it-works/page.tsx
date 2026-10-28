import type { Metadata } from "next";
import { IconBolt, IconChat, IconCheck, IconCode, IconRuns, IconServer, IconShield } from "@/components/Icons";
import { EpisodeDiagram, ThreeSteps } from "@/components/site/diagram";
import { Cta, CtaBand, Heading, More, PageHero, Section, Serif } from "@/components/site/kit";
import { Code } from "@/components/ui";

export const metadata: Metadata = {
  title: "How it works · AgentCrucible",
  description: "Gateways that record and control every model and tool call, a clean sandbox per test, outcome-based grading and statistics that tell a real regression from noise.",
};

export default function HowItWorks() {
  return (
    <>
      <PageHero eyebrow="How it works" toc={[["gateways", "The gateways"], ["sandbox", "A clean world every time"], ["grading", "Grading"], ["statistics", "Statistics"], ["where", "Where it runs"]]} title={<>It sits between your agent and <Serif>the outside world</Serif></>}
        lead="Agents talk to two things: a model API and their tools. AgentCrucible stands in for both, so it can record every call, control what comes back, and grade what actually changed, without touching your agent's code.">
        <Cta href="/start/" primary>Connect your agent</Cta>
        <Cta href="/demo/">See a real run</Cta>
      </PageHero>

      <Section>
        <ThreeSteps />
        <div className="mt-6"><EpisodeDiagram /></div>
      </Section>

      <Gateways />
      <Sandbox />
      <Grading />
      <Statistics />
      <WhereItRuns />
      <CtaBand />
    </>
  );
}

function Gateways() {
  return (
    <Section id="gateways" className="border-t border-line/60">
      <Heading eyebrow="1 · The gateways" title={<>Every call is recorded. <Serif>Anything</Serif> can be controlled.</>}
        lead="Your agent gets two kinds of addresses through environment variables it already reads. Both point at AgentCrucible, which forwards the traffic and keeps a full trajectory of the episode." />
      <div className="grid gap-5 lg:grid-cols-2">
        <div className="card p-6 sm:p-7">
          <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-ember/12 text-ember"><IconBolt /></span><h3 className="text-[19px] font-semibold tracking-tight">Model gateway</h3></div>
          <ul className="mt-5 space-y-3 text-[14.5px] text-mute">
            <Li>Speaks <b className="text-fg">OpenAI Chat Completions</b>, the <b className="text-fg">OpenAI Responses API</b> and <b className="text-fg">Anthropic Messages</b>, streamed or not.</Li>
            <Li>Forces one model for every call, so the same suite compares <code className="font-mono text-[13px] text-fg">qwen2.5:7b</code> with <code className="font-mono text-[13px] text-fg">gpt-4.1</code> fairly.</Li>
            <Li>Records tokens, latency and tool calls per call, for budget checks and cost per episode.</Li>
            <Li>Caches responses: <code className="font-mono text-[13px] text-fg">--cache replay</code> re-runs a whole suite with no model calls at all.</Li>
          </ul>
          <div className="mt-6"><Code copy={false} title="your agent's environment" code={`OPENAI_BASE_URL=http://127.0.0.1:<port>/ep/<episode>/v1\nANTHROPIC_BASE_URL=http://127.0.0.1:<port>/ep/<episode>`} /></div>
        </div>
        <div className="card p-6 sm:p-7">
          <div className="flex items-center gap-3"><span className="flex h-10 w-10 items-center justify-center rounded-xl bg-ember/12 text-ember"><IconServer /></span><h3 className="text-[19px] font-semibold tracking-tight">Tool gateway</h3></div>
          <ul className="mt-5 space-y-3 text-[14.5px] text-mute">
            <Li>Proxies every <b className="text-fg">MCP server</b>: local ones started fresh per episode, or remote ones reached by URL with your auth headers.</Li>
            <Li><b className="text-fg">Mocks</b> a tool&apos;s result, <b className="text-fg">blocks</b> tools the agent must never call, and <b className="text-fg">injects</b> attack text into real tool output.</Li>
            <Li>Serves <b className="text-fg">HTTP mocks</b> for third-party APIs (payments, email, CRM) and records every request.</Li>
            <Li>Records arguments, results, errors and timing of every tool call.</Li>
          </ul>
          <div className="mt-6"><Code copy={false} title="your agent's environment" code={`CRUCIBLE_MCP_SHOP_URL=http://127.0.0.1:<port>/ep/<episode>/mcp/shop\nCRUCIBLE_HTTP_PAYMENTS_URL=http://127.0.0.1:<port>/ep/<episode>/http/payments`} /></div>
        </div>
      </div>
    </Section>
  );
}

function Sandbox() {
  const rows: [string, string, string][] = [
    ["A SQLite database", "fixtures: { shop: seed.sql }", "New file from your seed SQL"],
    ["A Postgres database", "fixtures: { shop: { postgres: seed.sql } }", "CREATE DATABASE, seed, drop afterwards"],
    ["A code repository", "workspace: { path: repos/app, ref: v1.4 }", "Fresh copy or clone, with a baseline commit"],
    ["Files on disk", "workspace: { path: fixtures/inbox }", "Any folder, copied fresh"],
    ["A third-party API", "http_mocks: { payments: [ … ] }", "Canned responses, every request recorded"],
    ["A fake tool result", "mocks: { send_email: { status: sent } }", "Returned instead of running the tool"],
    ["A forbidden tool", "deny_tools: [drop_table]", "Blocked and recorded"],
    ["An attack", "inject: { read_file: \"Ignore previous…\" }", "Appended to the real tool output"],
  ];
  return (
    <Section id="sandbox" className="border-t border-line/60">
      <Heading eyebrow="2 · A clean world every time" title={<>Each attempt starts from <Serif>exactly</Serif> the same state</>}
        lead="Tests that share a database pass or fail depending on what ran before them. Every episode gets its own fresh copy of whatever the scenario needs, so a failure means the agent, not leftovers." />
      <div className="card overflow-hidden">
        <div className="hidden grid-cols-[1fr_1.4fr_1.1fr] gap-4 border-b border-line bg-panel-2/60 px-5 py-3 text-[12px] font-medium uppercase tracking-[0.1em] text-dim md:grid">
          <span>Your agent needs</span><span>In the scenario</span><span>Per episode</span>
        </div>
        {rows.map(([need, yaml, per]) => (
          <div key={need} className="grid gap-1.5 border-b border-line/60 px-5 py-3.5 text-[14px] last:border-0 md:grid-cols-[1fr_1.4fr_1.1fr] md:items-center md:gap-4">
            <span className="font-medium">{need}</span>
            <code className="break-words font-mono text-[12.5px] text-ember/90">{yaml}</code>
            <span className="text-mute">{per}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Grading() {
  const groups = [
    { icon: IconCheck, t: "State", b: "What actually changed.", ex: ["state.sql: the refund row exists", "state.command: the test suite passes", "state.git_diff: tests/ untouched", "http.called: payment API hit once"] },
    { icon: IconRuns, t: "Trajectory", b: "What the agent did, and when.", ex: ["tool_called / tool_not_called", "call_order: look up, then refund", "not_before_turn: confirm first", "no_tool_errors, max_tool_calls"] },
    { icon: IconChat, t: "Output", b: "What the agent said.", ex: ["contains / not_contains", "regex: “1–2 business days”", "judge.rubric: polite and concise"] },
    { icon: IconBolt, t: "Budget", b: "What it cost.", ex: ["max_llm_calls", "max_tokens", "max_duration_s", "max_cost_usd"] },
  ];
  return (
    <Section id="grading" className="border-t border-line/60">
      <Heading eyebrow="3 · Grading" title={<>Check the outcome, <Serif>not the transcript</Serif></>}
        lead="An agent that says “done” and did nothing passes any test that reads its reply. Checks look at the database, the repo, the tool calls and the budget. Any check can be soft (reported, never failing)." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {groups.map(({ icon: Icon, t, b, ex }) => (
          <div key={t} className="card p-5">
            <Icon className="h-5 w-5 text-ember" />
            <div className="mt-3 text-[16px] font-semibold">{t}</div>
            <p className="text-[13.5px] text-mute">{b}</p>
            <ul className="mt-4 space-y-1.5">
              {ex.map((x) => <li key={x} className="rounded-lg bg-panel-2/70 px-2.5 py-1.5 font-mono text-[11.5px] text-fg/85">{x}</li>)}
            </ul>
          </div>
        ))}
      </div>
      <div className="mt-5 rounded-xl border border-line bg-panel-2/40 p-5 text-[14px] leading-relaxed text-mute">
        <b className="text-fg">LLM judges are kept honest.</b> Label a few dozen episodes yourself with <code className="font-mono text-[12.5px] text-fg">crucible label</code>, and{" "}
        <code className="font-mono text-[12.5px] text-fg">crucible calibrate</code> measures how often the judge agrees with you (Cohen&apos;s κ). Below κ 0.6 its checks are automatically demoted to non-blocking.
      </div>
    </Section>
  );
}

function Statistics() {
  return (
    <Section id="statistics" className="border-t border-line/60">
      <Heading eyebrow="4 · Statistics" title={<>Better, worse, or <Serif>not sure yet</Serif></>}
        lead="Agents are random. The same prompt passes four times and fails the fifth. So every scenario runs several times, and changes are judged with the same statistics you would use for an A/B test." />
      <div className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
        <div className="card p-6 sm:p-7">
          <div className="grid gap-5 sm:grid-cols-2">
            <Metric k="pass@1" v="78%" d="Average chance one attempt succeeds. What a single-run eval reports." />
            <Metric k="pass^5" v="50%" d="Share of scenarios where all five attempts succeed. What your users experience." />
          </div>
          <p className="mt-5 border-t border-line pt-5 text-[14px] leading-relaxed text-mute">
            Both numbers come from the same run of our example support agent. The 28-point gap is invisible if you test each scenario once.
          </p>
        </div>
        <div className="card p-6 sm:p-7">
          <div className="text-[15px] font-semibold">How a change is judged</div>
          <ol className="mt-4 space-y-3 text-[14px] text-mute">
            <Num n={1}>Overall: difference in pass rate with a bootstrap 95% confidence interval.</Num>
            <Num n={2}>Per scenario: Fisher&apos;s exact test, corrected for testing many scenarios at once (Benjamini–Hochberg).</Num>
            <Num n={3}>Not enough evidence? The verdict is <b className="text-fg">inconclusive</b>, with an estimate of how many attempts would settle it.</Num>
            <Num n={4}>The gate fails only on what you choose, usually a significant <b className="text-fg">regression</b>.</Num>
          </ol>
        </div>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-4">
        {[
          ["regressed", "text-bad", "Significantly worse"],
          ["improved", "text-ok", "Significantly better"],
          ["inconclusive", "text-warn", "Needs k≈N more attempts"],
          ["unchanged", "text-mute", "No meaningful difference"],
        ].map(([v, c, d]) => (
          <div key={v} className="rounded-xl border border-line bg-panel-2/50 px-4 py-3">
            <div className={`font-mono text-[13px] ${c}`}>{v}</div>
            <div className="text-[13px] text-mute">{d}</div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function WhereItRuns() {
  const places = [
    { icon: IconCode, t: "Your laptop", b: "pip install, crucible run. Free with Ollama; HTML report with every trajectory.", code: "crucible run -k 5 --compare baseline" },
    { icon: IconRuns, t: "The dashboard", b: "docker compose up: start runs, watch progress, read verdicts, audit servers.", code: "open http://localhost:8080/dashboard/" },
    { icon: IconShield, t: "Pull requests", b: "A GitHub Action runs the suite, comments the verdict and fails the check on a regression.", code: "uses: prosws2210/AgentCrucible@main" },
    { icon: IconServer, t: "Kubernetes", b: "A Helm chart shards big suites across pods and merges the results into one gate.", code: "helm install crucible deploy/helm/agentcrucible" },
  ];
  return (
    <Section id="where" className="border-t border-line/60">
      <Heading eyebrow="5 · Where it runs" title={<>Same engine, <Serif>four places</Serif></>} />
      <div className="grid gap-4 sm:grid-cols-2">
        {places.map(({ icon: Icon, t, b, code }) => (
          <div key={t} className="card flex flex-col p-6">
            <div className="flex items-center gap-3"><Icon className="h-5 w-5 text-ember" /><h3 className="text-[17px] font-semibold">{t}</h3></div>
            <p className="mb-4 mt-2 text-[14.5px] leading-relaxed text-mute">{b}</p>
            <div className="mt-auto rounded-lg bg-panel-2 px-3 py-2 font-mono text-[12.5px] text-fg/85">{code}</div>
          </div>
        ))}
      </div>
      <div className="mt-8"><More href="/docs/">Set it up: the documentation</More></div>
    </Section>
  );
}

function Li({ children }: { children: React.ReactNode }) {
  return <li className="flex gap-3"><IconCheck className="mt-1 h-4 w-4 shrink-0 text-ok" /><span>{children}</span></li>;
}

function Num({ n, children }: { n: number; children: React.ReactNode }) {
  return <li className="flex gap-3"><span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-ember/15 font-mono text-[11px] text-ember">{n}</span><span>{children}</span></li>;
}

function Metric({ k, v, d }: { k: string; v: string; d: string }) {
  return (
    <div>
      <div className="font-mono text-[12px] text-ember">{k}</div>
      <div className="mt-1 text-[36px] font-semibold tracking-tight">{v}</div>
      <p className="mt-1 text-[13.5px] leading-relaxed text-mute">{d}</p>
    </div>
  );
}
