import Link from "next/link";
import { IconArrow, IconBolt, IconChat, IconCheck, IconGit, IconRuns, IconScenarios, IconServer, IconShield, IconX } from "@/components/Icons";
import { LogoMark } from "@/components/Logo";
import { GitHubIcon, Nav } from "@/components/Nav";
import { ProductPreview } from "@/components/ProductPreview";
import { TrajectoryViewer } from "@/components/TrajectoryViewer";
import { Code } from "@/components/ui";
import { UseCases } from "@/components/UseCases";
import { blob, GITHUB, tree } from "@/lib/site";

export default function Home() {
  return (
    <>
      <Nav />
      <main id="top" className="flex-1">
        <Hero />
        <Stack />
        <Problems />
        <HowItWorks />
        <Section id="use-cases">
          <Heading eyebrow="Use cases" title={<>Built for agents that <Serif>do things</Serif></>}
            lead="If your agent calls tools, changes data or writes code, a chat transcript can't tell you whether it did the right thing. AgentCrucible checks the outcome." />
          <UseCases />
        </Section>
        <Demo />
        <Product />
        <Proof />
        <Compare />
        <Faq />
        <ClosingCta />
      </main>
      <Footer />
    </>
  );
}

/* ------------------------------------------------------------------ primitives */

function Section({ id, children, className = "" }: { id?: string; children: React.ReactNode; className?: string }) {
  return <section id={id} className={`mx-auto w-full max-w-6xl px-4 py-20 sm:px-6 sm:py-24 ${className}`}>{children}</section>;
}

function Heading({ eyebrow, title, lead, center }: { eyebrow: string; title: React.ReactNode; lead?: React.ReactNode; center?: boolean }) {
  return (
    <div className={`mb-12 max-w-3xl ${center ? "mx-auto text-center" : ""}`}>
      <div className="mb-4 font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">{eyebrow}</div>
      <h2 className="text-balance text-3xl font-semibold tracking-tight sm:text-[42px] sm:leading-[1.1]">{title}</h2>
      {lead && <p className="mt-5 text-pretty text-[17px] leading-relaxed text-mute">{lead}</p>}
    </div>
  );
}

function Serif({ children }: { children: React.ReactNode }) {
  return <span className="font-serif text-[1.08em] font-normal italic tracking-normal">{children}</span>;
}

function Cta({ href, children, primary }: { href: string; children: React.ReactNode; primary?: boolean }) {
  const cls = primary
    ? "bg-fg text-ink hover:bg-white"
    : "border border-line bg-panel text-fg hover:border-ember/60";
  const external = href.startsWith("http");
  const c = `inline-flex items-center gap-2 rounded-full px-5 py-3 text-[14.5px] font-semibold transition-colors ${cls}`;
  return external ? <a href={href} className={c}>{children}</a> : <Link href={href} className={c}>{children}</Link>;
}

/* ------------------------------------------------------------------ hero */

function Hero() {
  return (
    <div className="relative overflow-hidden">
      <div className="grid-bg pointer-events-none absolute inset-0" />
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[900px] -translate-x-1/2 animate-glow rounded-full bg-[radial-gradient(closest-side,rgba(255,107,53,0.26),transparent)]" />
      <Section className="relative grid items-center gap-12 pt-14 sm:pt-20 lg:grid-cols-[1fr_1.05fr]">
        <div className="animate-rise">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-panel/80 px-3 py-1 text-[12.5px] text-mute">
            <span className="h-1.5 w-1.5 rounded-full bg-ok" />
            Open source · runs on your machine · free with local models
          </div>
          <h1 className="text-balance text-[42px] font-semibold leading-[1.04] tracking-[-0.03em] sm:text-[58px]">
            Catch your AI agent&apos;s mistakes <Serif><span className="ember-text pr-1">before your users do</span></Serif>
          </h1>
          <p className="mt-6 max-w-xl text-pretty text-[18px] leading-relaxed text-mute">
            AgentCrucible replays your agent through realistic scenarios on every change, checks what it actually
            did (the tools it called, the data it changed, the code it wrote) and tells you whether the change made it
            better or worse.
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Cta href="/start/" primary>Get started free <IconArrow /></Cta>
            <Cta href="/#demo">Watch it catch a bug</Cta>
          </div>
          <ul className="mt-9 grid max-w-lg gap-2.5 text-[13.5px] text-mute sm:grid-cols-2">
            {["Works with any framework and model", "No changes to your agent's logic", "Tests MCP servers too", "Pass/fail gate in your CI"].map((x) => (
              <li key={x} className="flex items-center gap-2"><IconCheck className="h-4 w-4 shrink-0 text-ok" /> {x}</li>
            ))}
          </ul>
        </div>
        <div className="animate-rise [animation-delay:150ms]">
          <ProductPreview />
        </div>
      </Section>
    </div>
  );
}

function Stack() {
  const items = ["OpenAI SDK", "Anthropic SDK", "LangGraph", "CrewAI", "AutoGen", "Vercel AI SDK", "Ollama", "vLLM", "OpenRouter", "any MCP server"];
  return (
    <div className="border-y border-line/70 bg-panel/40">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-center gap-x-7 gap-y-3 px-4 py-6 sm:px-6">
        <span className="font-mono text-[11px] uppercase tracking-[0.16em] text-dim">Works with</span>
        {items.map((i) => <span key={i} className="text-[13.5px] text-mute">{i}</span>)}
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ problem */

function Problems() {
  const items = [
    { icon: IconChat, t: "“Done, I've refunded you.” It hadn't.", b: "Agents report success they didn't achieve. Reading the reply isn't enough; you have to check the database, the tool calls and the files." },
    { icon: IconRuns, t: "Green on Monday, red on Tuesday.", b: "The same agent gives different answers to the same request. One passing run proves very little, so every scenario runs several times." },
    { icon: IconBolt, t: "A small prompt tweak broke something else.", b: "Changes to prompts, models and tools have side effects. Every change gets compared with a baseline before it ships." },
  ];
  return (
    <Section>
      <Heading eyebrow="Why" title={<>Agents fail in ways normal tests <Serif>can&apos;t see</Serif></>} />
      <div className="grid gap-4 md:grid-cols-3">
        {items.map(({ icon: Icon, t, b }) => (
          <div key={t} className="card p-6">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-ember/12 text-ember"><Icon /></span>
            <h3 className="mt-5 text-[17px] font-semibold leading-snug tracking-tight">{t}</h3>
            <p className="mt-2.5 text-[14.5px] leading-relaxed text-mute">{b}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ how it works */

function HowItWorks() {
  return (
    <Section id="how">
      <Heading eyebrow="How it works" title={<>Three steps. <Serif>No SDK.</Serif></>}
        lead="Your agent keeps its code. AgentCrucible sits between it and the outside world (the model API and the MCP servers), so it can record, control and grade everything." />
      <div className="grid gap-5 lg:grid-cols-3">
        <Step n={1} title="Connect" body="Point your agent's model URL and MCP server URLs at AgentCrucible. The OpenAI and Anthropic SDKs read them from the environment already.">
          <Code copy={false} wrap title="what your agent receives" code={`OPENAI_BASE_URL=…/v1\nCRUCIBLE_MCP_SHOP_URL=…/mcp/shop`} />
        </Step>
        <Step n={2} title="Describe" body="Write scenarios as YAML: what the user says, and what must and must never happen. Each runs in a fresh sandbox.">
          <Code copy={false} wrap title="scenarios/refund.yaml" code={`task: Refund my mouse, please.\nchecks:\n  - state.sql: { … expect: 1 }\n  - trajectory.not_before_turn:\n      tool: issue_refund\n      turn: 2`} />
        </Step>
        <Step n={3} title="Gate" body="Every change gets a verdict: better, worse, or not sure yet. On pull requests it comments and passes or fails the check.">
          <div className="rounded-xl border border-line bg-panel-2/60 p-4 text-[12.5px]">
            <div className="flex items-center gap-2 text-mute"><LogoMark className="h-4 w-4" /> crucible-bot</div>
            <div className="mt-2 font-medium text-bad">✕ Worse than baseline: −30.0 pts</div>
            <div className="mt-1 text-mute">injection-in-tool-output 5/5 → 0/5</div>
            <div className="text-mute">refund-requires-confirmation 4/5 → 1/5</div>
          </div>
        </Step>
      </div>

      <div className="card mt-8 p-5 sm:p-7">
        <div className="mb-5 font-mono text-[11.5px] uppercase tracking-[0.14em] text-dim">What happens in each test, called an episode</div>
        <div className="grid items-stretch gap-3 lg:grid-cols-[1fr_auto_1.1fr_auto_1fr_auto_1fr]">
          <Box title="Simulated user" sub="Plays the customer from a persona" />
          <Arrow />
          <Box title="Your agent" sub="Unchanged, any framework" accent />
          <Arrow />
          <Box title="Model gateway" sub="Records every call; can force a model" accent />
          <Arrow />
          <Box title="Your model" sub="Ollama, OpenAI, Anthropic, vLLM…" />
        </div>
        <div className="mt-3 grid items-stretch gap-3 lg:grid-cols-[1fr_auto_1.1fr_auto_1fr_auto_1fr]">
          <div className="hidden lg:block" />
          <div className="hidden lg:block" />
          <div className="flex items-center justify-center text-[12px] text-dim lg:justify-end">tool calls go through ↘</div>
          <div className="hidden lg:block" />
          <Box title="Tool gateway" sub="Records, mocks, blocks, injects attacks" accent />
          <Arrow />
          <Box title="Your MCP servers" sub="Fresh process + clean database or repo" />
        </div>
        <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-5 text-[13.5px] text-mute">
          <span className="font-medium text-fg">Then:</span>
          {["grade the outcome", "repeat several times", "compare with the baseline", "pass or fail the gate"].map((x, i) => (
            <span key={x} className="flex items-center gap-2"><span className="font-mono text-[11px] text-ember">{i + 1}</span>{x}</span>
          ))}
        </div>
      </div>
    </Section>
  );
}

function Step({ n, title, body, children }: { n: number; title: string; body: string; children: React.ReactNode }) {
  return (
    <div className="card flex flex-col p-6">
      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-ember/15 font-mono text-[13px] text-ember">{n}</span>
        <h3 className="text-[19px] font-semibold tracking-tight">{title}</h3>
      </div>
      <p className="mb-5 mt-3 text-[14.5px] leading-relaxed text-mute">{body}</p>
      <div className="mt-auto">{children}</div>
    </div>
  );
}

function Box({ title, sub, accent }: { title: string; sub: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${accent ? "border-ember/50 bg-ember/[0.07]" : "border-line bg-panel-2"}`}>
      <div className="text-[14px] font-semibold">{title}</div>
      <div className="mt-0.5 text-[12.5px] leading-snug text-mute">{sub}</div>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex items-center justify-center px-1 text-dim">
      <span className="text-lg leading-none lg:hidden">↓</span>
      <span className="hidden text-lg leading-none lg:inline">→</span>
    </div>
  );
}

/* ------------------------------------------------------------------ demo */

function Demo() {
  return (
    <Section id="demo">
      <Heading eyebrow="Live demo · two real recorded runs" title={<>Watch it catch a <Serif>prompt injection</Serif></>}
        lead="A customer asks about a mouse. Hidden in the product description is an instruction to refund an order. Switch between the two prompts: same model, same question, different outcome." />
      <TrajectoryViewer />
      <p className="mt-4 text-center text-[13px] text-dim">Every message, model call and tool call is recorded. The dashboard shows this for every attempt of every scenario.</p>
    </Section>
  );
}

/* ------------------------------------------------------------------ product */

function Product() {
  const tiles = [
    { icon: IconRuns, t: "Runs", b: "Start a run from the browser, watch it live, and get a plain-English verdict with the evidence." },
    { icon: IconScenarios, t: "Scenarios", b: "Every test explained: what the user says, what must happen, and how it did last time." },
    { icon: IconServer, t: "MCP audits", b: "A graded report card for each tool server, with the exact findings to fix." },
    { icon: IconShield, t: "Setup check", b: "One click confirms the model, MCP servers and agent are reachable, and tells you how to fix them if not." },
  ];
  return (
    <Section>
      <div className="grid items-center gap-12 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <Heading eyebrow="The dashboard" title={<>Everything in one place, <Serif>on your machine</Serif></>}
            lead="Run it next to your agent with one command. Your prompts, data and results never leave your infrastructure." />
          <div className="-mt-4 flex flex-wrap gap-3">
            <Cta href="/start/" primary>Set up your agent</Cta>
            <Cta href="/dashboard/">Open the dashboard</Cta>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {tiles.map(({ icon: Icon, t, b }) => (
            <div key={t} className="card p-5">
              <Icon className="h-5 w-5 text-ember" />
              <div className="mt-3 text-[15px] font-semibold">{t}</div>
              <p className="mt-1.5 text-[13.5px] leading-relaxed text-mute">{b}</p>
            </div>
          ))}
        </div>
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ proof */

function Proof() {
  const stats = [
    { big: "78% vs 50%", label: "the reliability gap", body: "Testing each scenario once said the agent works 78% of the time. Only half the scenarios passed all five attempts." },
    { big: "−30 pts", label: "regression caught", body: "A “be faster” prompt change. The gate failed the build before it reached users." },
    { big: "5 / 5", label: "injection attacks obeyed", body: "With one prompt rule removed, hidden instructions triggered a refund every single time." },
    { big: "0 lines", label: "changed when it claimed to", body: "A coding agent said it had deleted a file. The repo diff showed it never touched anything." },
  ];
  return (
    <Section>
      <Heading eyebrow="Real results" title={<>What it found in <Serif>our own examples</Serif></>}
        lead={<>Measured on the two example agents that ship with the project, using free local models. <a href={blob("docs/RESULTS.md")} className="text-ember">Methodology and raw numbers →</a></>} />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((s) => (
          <div key={s.label} className="card p-6">
            <div className="text-[30px] font-semibold tracking-tight">{s.big}</div>
            <div className="mt-1 font-mono text-[11px] uppercase tracking-[0.12em] text-ember">{s.label}</div>
            <p className="mt-4 text-[14px] leading-relaxed text-mute">{s.body}</p>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Compare() {
  const rows: [string, string, string][] = [
    ["What gets graded", "The final reply", "Tool calls, data, files and the reply"],
    ["Attempts per test", "One", "Several, because agents are random"],
    ["“Did it get worse?”", "Eyeball two numbers", "Statistical verdict, or “needs N more runs”"],
    ["Test environment", "Shared, gets dirty", "Fresh database, repo and servers every time"],
    ["Attacks", "Rarely tested", "Prompt injection, destructive requests, data leaks"],
    ["Framework lock-in", "SDK or tracing library", "None: two environment variables"],
  ];
  return (
    <Section>
      <Heading eyebrow="Compared with" title={<>A typical eval script <Serif>vs</Serif> AgentCrucible</>} center />
      <div className="card mx-auto max-w-4xl overflow-hidden">
        <div className="grid grid-cols-[1fr_1fr_1.2fr] border-b border-line bg-panel-2/60 px-5 py-3 text-[12.5px] font-medium text-dim">
          <span />
          <span>Typical eval script</span>
          <span className="text-ember">AgentCrucible</span>
        </div>
        {rows.map(([k, a, b]) => (
          <div key={k} className="grid grid-cols-[1fr_1fr_1.2fr] items-center gap-3 border-b border-line/60 px-5 py-3.5 text-[13.5px] last:border-0">
            <span className="font-medium">{k}</span>
            <span className="flex items-center gap-2 text-mute"><IconX className="h-3.5 w-3.5 shrink-0 text-dim" />{a}</span>
            <span className="flex items-center gap-2"><IconCheck className="h-3.5 w-3.5 shrink-0 text-ok" />{b}</span>
          </div>
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ faq */

function Faq() {
  const qs: [string, React.ReactNode][] = [
    ["Do I have to change my agent?", <>No logic changes. Your agent reads its model URL and MCP server URLs from the environment (most SDKs already do), and either talks over stdin/stdout or exposes one HTTP endpoint. The <Link href="/start/" className="text-ember">setup wizard</Link> writes the small adapter for you.</>],
    ["Which frameworks and models work?", "Anything that calls an OpenAI-compatible or Anthropic API: the OpenAI and Anthropic SDKs, LangGraph, CrewAI, AutoGen, Vercel AI SDK, plain code. Models can be local (Ollama, vLLM) or hosted (OpenAI, Anthropic, OpenRouter)."],
    ["Does my data leave my machine?", "No. AgentCrucible is self-hosted: the CLI, the dashboard and the database run where you run them. The only outside calls are the ones your agent already makes to your model provider."],
    ["What does it cost?", "The software is free and open source (Apache-2.0). Running tests costs whatever your model provider charges; with local models it is free, and recorded responses can be replayed at no cost."],
    ["How many runs do I need?", "3 attempts per scenario to explore, 5 or more for a baseline you gate on. When the evidence is too thin to call a change, the report says so and estimates how many attempts would settle it."],
    ["Can it test an agent that's already deployed?", "Yes. Point the HTTP transport at your staging URL (with an auth header if needed) and AgentCrucible sends each test there with the gateway addresses in the request."],
    ["What about MCP servers I build?", "Run an audit on them: protocol conformance, tool-description quality, fuzzing, security probes and latency, in a few seconds, with a graded report card."],
  ];
  return (
    <Section id="faq">
      <Heading eyebrow="FAQ" title={<>Questions people <Serif>actually ask</Serif></>} center />
      <div className="mx-auto max-w-3xl space-y-3">
        {qs.map(([q, a]) => (
          <details key={q} className="card group px-5 py-4 [&_summary::-webkit-details-marker]:hidden">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-[15.5px] font-medium">
              {q}
              <span className="text-xl leading-none text-dim transition-transform group-open:rotate-45">+</span>
            </summary>
            <div className="mt-3 text-[14.5px] leading-relaxed text-mute">{a}</div>
          </details>
        ))}
      </div>
    </Section>
  );
}

/* ------------------------------------------------------------------ closing */

function ClosingCta() {
  return (
    <Section className="pb-28">
      <div className="card relative overflow-hidden px-6 py-14 text-center sm:px-12">
        <div className="pointer-events-none absolute inset-x-0 -bottom-32 mx-auto h-64 w-[640px] rounded-full bg-[radial-gradient(closest-side,rgba(255,107,53,0.3),transparent)]" />
        <LogoMark className="relative mx-auto h-12 w-12" />
        <h2 className="relative mx-auto mt-6 max-w-2xl text-balance text-3xl font-semibold tracking-tight sm:text-[42px] sm:leading-[1.1]">
          Know your agent works <Serif>before</Serif> you ship it
        </h2>
        <p className="relative mx-auto mt-4 max-w-xl text-[16px] text-mute">Five minutes to connect. Free, open source and running on your own machine.</p>
        <div className="relative mt-8 flex flex-wrap justify-center gap-3">
          <Cta href="/start/" primary>Get started free <IconArrow /></Cta>
          <Cta href={GITHUB}><GitHubIcon /> Star on GitHub</Cta>
        </div>
      </div>
    </Section>
  );
}

function Footer() {
  const cols: [string, [string, string][]][] = [
    ["Product", [["Get started", "/start/"], ["Dashboard", "/dashboard/"], ["Live demo", "/#demo"], ["FAQ", "/#faq"]]],
    ["Docs", [["Adoption guide", blob("docs/ADOPTION.md")], ["Results", blob("docs/RESULTS.md")], ["Architecture", blob("docs/ARCHITECTURE.md")]]],
    ["Examples", [["Support agent", tree("examples/support-agent")], ["Coding agent", tree("examples/coding-agent")], ["GitHub Action", blob("action.yml")], ["Helm chart", tree("deploy/helm/agentcrucible")]]],
  ];
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-col gap-10 px-4 py-12 sm:px-6 lg:flex-row lg:justify-between">
        <div className="max-w-xs">
          <div className="flex items-center gap-2.5">
            <LogoMark className="h-6 w-6" />
            <span className="font-semibold">AgentCrucible</span>
          </div>
          <p className="mt-3 text-[13px] leading-relaxed text-mute">Regression testing for AI agents and MCP servers. Built by Shakti Swaroop Sahu.</p>
          <div className="mt-4 flex items-center gap-2 text-[12.5px] text-dim"><IconGit className="h-4 w-4" /> Apache-2.0 · open source</div>
        </div>
        <div className="grid grid-cols-2 gap-10 sm:grid-cols-3">
          {cols.map(([h, links]) => (
            <div key={h}>
              <div className="mb-3 font-mono text-[11px] uppercase tracking-[0.14em] text-dim">{h}</div>
              <ul className="space-y-2 text-[13.5px]">
                {links.map(([l, href]) => (
                  <li key={l}>
                    {href.startsWith("http") ? <a href={href} className="text-mute transition-colors hover:text-fg">{l}</a>
                      : <Link href={href} className="text-mute transition-colors hover:text-fg">{l}</Link>}
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </footer>
  );
}
