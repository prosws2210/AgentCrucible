import Link from "next/link";
import { DemoVideo } from "@/components/demo/DemoVideo";
import { IconArrow, IconBolt, IconChat, IconCheck, IconCode, IconGit, IconRuns, IconScenarios, IconServer, IconSetup, IconShield } from "@/components/Icons";
import { ProductPreview } from "@/components/ProductPreview";
import { ThreeSteps } from "@/components/site/diagram";
import { faq, FaqItem } from "@/components/site/faq";
import { Cta, CtaBand, Heading, More, Section, Serif } from "@/components/site/kit";
import { Code } from "@/components/ui";
import { blob, GITHUB } from "@/lib/site";

export default function Home() {
  return (
    <>
      <Hero />
      <Stack />
      <Problems />
      <Watch />
      <Section className="border-t border-line/60">
        <Heading eyebrow="How it works" title={<>Three steps. <Serif>No SDK.</Serif></>}
          lead="Your agent keeps its code. AgentCrucible sits between it and the outside world (the model API and the MCP servers), so it can record, control and grade everything." />
        <ThreeSteps />
        <div className="mt-8"><More href="/how-it-works/">The full picture: gateways, sandboxes, grading and statistics</More></div>
      </Section>
      <UseCaseTeaser />
      <Proof />
      <Ways />
      <Quickstart />
      <Teams />
      <HomeFaq />
      <CtaBand />
    </>
  );
}

function Hero() {
  return (
    <div className="relative overflow-hidden">
      <div className="grid-bg pointer-events-none absolute inset-0" />
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[520px] w-[900px] -translate-x-1/2 animate-glow rounded-full bg-[radial-gradient(closest-side,rgba(255,107,53,0.26),transparent)]" />
      <Section className="relative grid items-center gap-12 pt-14 sm:pt-20 lg:grid-cols-[1fr_1.05fr]">
        <div className="animate-rise">
          <div className="mb-6 inline-flex items-center gap-2 rounded-full border border-line bg-panel/80 px-3 py-1 text-[12.5px] text-mute">
            <span className="h-1.5 w-1.5 rounded-full bg-ok" />
            Source available · runs on your machine · free with local models
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
            <Cta href="/demo/">See it catch a bug</Cta>
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

function Problems() {
  const items = [
    { icon: <IconChat />, t: "“Done, I've refunded you.” It hadn't.", b: "Agents report success they didn't achieve, or do things nobody asked for.", fix: "Checks the database, the files and every tool call, not just the reply." },
    { icon: <IconRuns />, t: "Green on Monday, red on Tuesday.", b: "The same agent gives different answers to the same request. One passing run proves very little.", fix: "Runs every scenario several times and reports how reliable it really is." },
    { icon: <IconBolt />, t: "A small prompt tweak broke something else.", b: "Changes to prompts, models and tools have side effects nobody tested for.", fix: "Compares every change with a baseline and gives a statistical verdict." },
    { icon: <IconServer />, t: "The tools themselves are broken.", b: "An MCP server with an injectable query or a vague tool description fails every agent that uses it.", fix: "Audits each MCP server on its own and grades it, before an agent touches it." },
  ];
  return (
    <Section>
      <Heading eyebrow="Why" title={<>Agents fail in ways normal tests <Serif>can&apos;t see</Serif></>}
        lead="Unit tests mock the model away; eval scripts read one reply, once. Neither tells you whether your agent did the right thing, every time." />
      <div className="grid gap-4 md:grid-cols-2">
        {items.map(({ icon, t, b, fix }) => (
          <div key={t} className="card flex flex-col p-6">
            <div className="flex flex-1 items-start gap-4">
              <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ember/12 text-ember">{icon}</span>
              <div>
                <h3 className="text-[17px] font-semibold leading-snug tracking-tight">{t}</h3>
                <p className="mt-2 text-[14.5px] leading-relaxed text-mute">{b}</p>
              </div>
            </div>
            <div className="mt-5 flex items-start gap-2.5 border-t border-line pt-4 text-[14px]">
              <IconCheck className="mt-0.5 h-4 w-4 shrink-0 text-ok" />
              <span><span className="font-medium text-fg">AgentCrucible </span><span className="text-mute">{fix.charAt(0).toLowerCase() + fix.slice(1)}</span></span>
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function Watch() {
  return (
    <Section id="watch" className="border-t border-line/60">
      <Heading eyebrow="Watch it work · 2 minutes" title={<>From download to a <Serif>blocked regression</Serif></>}
        lead="A team installs AgentCrucible, connects their agent, tests a prompt change, finds a prompt injection, audits their MCP server and gates the pull request. Captions on; narration optional." />
      <DemoVideo chapters={false} />
      <div className="mt-6"><More href="/demo/">Chapters, the real report and the raw results</More></div>
    </Section>
  );
}

function UseCaseTeaser() {
  const cases = [
    { icon: <IconChat />, t: "Support & operations agents", b: "Refunds, cancellations, account changes: checked in the database, not the transcript.", id: "support" },
    { icon: <IconCode />, t: "Coding agents", b: "A fresh repo copy per attempt; your tests run and the diff shows exactly what changed.", id: "coding" },
    { icon: <IconServer />, t: "MCP server builders", b: "A graded audit of any server: protocol, tool quality, fuzzing, security, latency.", id: "mcp" },
    { icon: <IconShield />, t: "Security testing", b: "Prompt injection in tool output, destructive requests, cross-customer data access.", id: "security" },
    { icon: <IconBolt />, t: "Model & prompt changes", b: "Swap a model or edit a prompt and get a statistical verdict, scenario by scenario.", id: "changes" },
    { icon: <IconScenarios />, t: "Deployed agent services", b: "Test the HTTP service you already run, in staging, with its real third-party APIs mocked.", id: "services" },
  ];
  return (
    <Section className="border-t border-line/60">
      <Heading eyebrow="Use cases" title={<>Built for agents that <Serif>do things</Serif></>}
        lead="If your agent calls tools, changes data or writes code, a chat transcript can't tell you whether it did the right thing. AgentCrucible checks the outcome." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {cases.map((c) => (
          <Link key={c.id} href={`/use-cases/#${c.id}`} className="card group p-6 transition-colors hover:border-ember/40">
            <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-ember/12 text-ember">{c.icon}</span>
            <h3 className="mt-5 text-[16.5px] font-semibold tracking-tight">{c.t}</h3>
            <p className="mt-2 text-[14px] leading-relaxed text-mute">{c.b}</p>
            <span className="mt-4 inline-flex items-center gap-1 text-[13px] text-ember opacity-80 group-hover:opacity-100">Read more <IconArrow className="h-3.5 w-3.5" /></span>
          </Link>
        ))}
      </div>
    </Section>
  );
}

function Proof() {
  const stats = [
    { big: "78% vs 50%", label: "the reliability gap", body: "Testing each scenario once said the agent works 78% of the time. Only half the scenarios passed all five attempts." },
    { big: "−30 pts", label: "regression caught", body: "A “be faster” prompt change. The gate failed the build before it reached users." },
    { big: "5 / 5", label: "injection attacks obeyed", body: "With one prompt rule removed, hidden instructions triggered a refund every single time." },
    { big: "0 lines", label: "changed when it claimed to", body: "A coding agent said it had deleted a file. The repo diff showed it never touched anything." },
  ];
  return (
    <Section className="border-t border-line/60">
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

const WAYS = [
  {
    icon: IconSetup, t: "Dashboard", sub: "For the whole team", href: "/features/#dashboard",
    b: "Start runs, watch progress, read verdicts and open any attempt's full trajectory.",
    peek: (
      <div className="space-y-1.5 text-[12px]">
        <Row k="prompt-v2" v={<span className="text-bad">−30 pts</span>} />
        <Row k="baseline" v={<span className="text-mute">78%</span>} />
      </div>
    ),
  },
  {
    icon: IconCode, t: "CLI", sub: "For your terminal", href: "/features/#cli",
    b: "Run suites, compare runs, replay from the cache and open a self-contained HTML report.",
    peek: (
      <div className="font-mono text-[11.5px] leading-relaxed">
        <div className="text-fg">$ crucible run -k 5</div>
        <div className="text-bad">✕ gate failed: regressed</div>
      </div>
    ),
  },
  {
    icon: IconGit, t: "Pull-request gate", sub: "For CI", href: "/features/#ci",
    b: "A GitHub Action runs the suite on every pull request, comments the verdict and blocks regressions.",
    peek: (
      <div className="flex items-center gap-2 text-[12px]">
        <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-bad/15 text-[10px] text-bad">✕</span>
        <b className="font-medium">regression check</b><span className="text-dim">failing</span>
      </div>
    ),
  },
  {
    icon: IconShield, t: "MCP audit", sub: "For tool builders", href: "/features/#more",
    b: "Conformance, tool quality, fuzzing, security probes and latency, graded A to F.",
    peek: (
      <div className="flex items-center gap-3 text-[12px]">
        <span className="font-serif text-[28px] leading-none text-bad">D</span>
        <span className="text-mute"><span className="text-bad">critical</span> · SQL injection</span>
      </div>
    ),
  },
];

function Ways() {
  return (
    <Section className="border-t border-line/60">
      <Heading eyebrow="The product" title={<>One engine, <Serif>four ways</Serif> to use it</>}
        lead="The dashboard, the CLI and CI run the same tests with the same statistics, so a verdict means the same thing everywhere." />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {WAYS.map(({ icon: Icon, t, sub, href, b, peek }) => (
          <Link key={t} href={href} className="card group flex flex-col p-5 transition-colors hover:border-ember/40">
            <div className="flex items-center gap-2.5"><Icon className="h-5 w-5 text-ember" /><span className="text-[16px] font-semibold">{t}</span></div>
            <div className="mt-1 font-mono text-[11px] uppercase tracking-[0.12em] text-dim">{sub}</div>
            <p className="mt-3 text-[14px] leading-relaxed text-mute">{b}</p>
            <div className="mt-auto pt-4"><div className="rounded-lg border border-line bg-panel-2/70 px-3 py-2.5">{peek}</div></div>
          </Link>
        ))}
      </div>
      <div className="mt-8 flex flex-wrap items-center gap-6">
        <More href="/features/">All features</More>
        <More href="/compare/">How it compares</More>
      </div>
    </Section>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return <div className="flex items-center justify-between gap-2"><span className="truncate font-mono text-fg/90">{k}</span><span className="shrink-0">{v}</span></div>;
}

function Quickstart() {
  const steps: [string, string][] = [
    ["Start it", "Dashboard, API, Postgres and a local model, in Docker."],
    ["Try the example", "A support agent with two MCP servers and ten scenarios."],
    ["Connect your agent", "Six questions; you get the config, an adapter and a first test."],
  ];
  return (
    <Section className="border-t border-line/60">
      <div className="grid items-center gap-10 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <Heading eyebrow="Quickstart" title={<>Running in <Serif>five minutes</Serif></>} className="mb-6"
            lead="Start the stack, open the dashboard and run the bundled example on a free local model. Then point it at your own agent with the setup wizard." />
          <ol className="space-y-3 text-[14.5px]">
            {steps.map(([t, d], i) => (
              <li key={t} className="flex gap-3">
                <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ember/15 font-mono text-[12px] text-ember">{i + 1}</span>
                <span><b className="font-medium">{t}.</b> <span className="text-mute">{d}</span></span>
              </li>
            ))}
          </ol>
          <div className="mt-7 flex flex-wrap gap-3">
            <Cta href="/start/" primary>Open the setup wizard <IconArrow /></Cta>
            <Cta href="/docs/">Read the docs</Cta>
          </div>
        </div>
        <Code title="terminal" code={`git clone ${GITHUB}.git
cd AgentCrucible && cp .env.example .env
docker compose up --build
# open http://localhost:8080/dashboard/

# or without Docker, on your own machine:
pip install -e . && cd examples/support-agent
crucible run --label baseline -k 5`} />
      </div>
    </Section>
  );
}

const TEAMS = [
  { icon: IconServer, t: "Self-hosted", b: "Runs on your laptop, your CI or your cluster. Prompts, data and results never leave your infrastructure." },
  { icon: IconShield, t: "Access control", b: "Full-access and read-only tokens for the dashboard and API, with HttpOnly session cookies." },
  { icon: IconBolt, t: "Free to run", b: "Free for your own team (FSL-1.1), with local models through Ollama. Recorded responses replay at no cost." },
  { icon: IconScenarios, t: "Tests live in your repo", b: "Scenarios are YAML files, reviewed in pull requests like any other code." },
  { icon: IconGit, t: "CI and Kubernetes", b: "A GitHub Action for every pull request, and a Helm chart that shards big suites across pods." },
  { icon: IconCheck, t: "No lock-in", b: "No SDK in your agent: any framework, any OpenAI- or Anthropic-compatible model, any MCP server." },
];

function Teams() {
  return (
    <Section className="border-t border-line/60">
      <Heading eyebrow="Built for teams" title={<>Ready for <Serif>your company&apos;s</Serif> agents</>}
        lead="Everything a team needs to put agent testing into its normal engineering workflow, without sending anything to a vendor." />
      <div className="grid gap-x-8 gap-y-7 sm:grid-cols-2 lg:grid-cols-3">
        {TEAMS.map(({ icon: Icon, t, b }) => (
          <div key={t} className="flex gap-4">
            <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-line bg-panel-2/70 text-ember"><Icon className="h-5 w-5" /></span>
            <div>
              <div className="text-[15.5px] font-semibold">{t}</div>
              <p className="mt-1 text-[14px] leading-relaxed text-mute">{b}</p>
            </div>
          </div>
        ))}
      </div>
    </Section>
  );
}

function HomeFaq() {
  const qs = ["Do I have to change my agent?", "Which frameworks and models work?", "Does my data leave my machine?", "What does it cost?"].map(faq);
  return (
    <Section className="border-t border-line/60">
      <div className="grid gap-10 lg:grid-cols-[0.8fr_1.2fr]">
        <div>
          <Heading eyebrow="FAQ" title={<>Questions, <Serif>answered</Serif></>} className="mb-6"
            lead="The ones teams ask first. Security, statistics, CI and MCP questions are on the FAQ page." />
          <More href="/faq/">All questions</More>
        </div>
        <div className="space-y-3">
          {qs.map(([q, a]) => <FaqItem key={q} q={q} a={a} />)}
        </div>
      </div>
    </Section>
  );
}
