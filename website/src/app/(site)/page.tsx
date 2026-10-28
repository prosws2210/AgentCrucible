import Link from "next/link";
import { IconArrow, IconBolt, IconChat, IconCheck, IconCode, IconRuns, IconScenarios, IconServer, IconShield } from "@/components/Icons";
import { ProductPreview } from "@/components/ProductPreview";
import { EpisodeDiagram, ThreeSteps } from "@/components/site/diagram";
import { Cta, CtaBand, Heading, More, Section, Serif, Tile } from "@/components/site/kit";
import { TrajectoryViewer } from "@/components/TrajectoryViewer";
import { blob } from "@/lib/site";

export default function Home() {
  return (
    <>
      <Hero />
      <Stack />
      <Problems />
      <Section>
        <Heading eyebrow="How it works" title={<>Three steps. <Serif>No SDK.</Serif></>}
          lead="Your agent keeps its code. AgentCrucible sits between it and the outside world (the model API and the MCP servers), so it can record, control and grade everything." />
        <ThreeSteps />
        <div className="mt-6"><EpisodeDiagram /></div>
        <div className="mt-8"><More href="/how-it-works/">The full picture: gateways, sandboxes, grading and statistics</More></div>
      </Section>
      <UseCaseTeaser />
      <Section>
        <Heading eyebrow="Live demo · two real recorded runs" title={<>Watch it catch a <Serif>prompt injection</Serif></>}
          lead="A customer asks about a mouse. Hidden in the product description is an instruction to refund an order. Switch between the two prompts: same model, same question, different outcome." />
        <TrajectoryViewer />
        <div className="mt-8"><More href="/demo/">More from the demo: the PR comment, the full report and an MCP audit</More></div>
      </Section>
      <Proof />
      <FeatureTeaser />
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
  return (
    <Section>
      <Heading eyebrow="Why" title={<>Agents fail in ways normal tests <Serif>can&apos;t see</Serif></>} />
      <div className="grid gap-4 md:grid-cols-3">
        <Tile icon={<IconChat />} title="“Done, I've refunded you.” It hadn't.">
          Agents report success they didn&apos;t achieve. Reading the reply isn&apos;t enough; you have to check the database, the tool calls and the files.
        </Tile>
        <Tile icon={<IconRuns />} title="Green on Monday, red on Tuesday.">
          The same agent gives different answers to the same request. One passing run proves very little, so every scenario runs several times.
        </Tile>
        <Tile icon={<IconBolt />} title="A small prompt tweak broke something else.">
          Changes to prompts, models and tools have side effects. Every change gets compared with a baseline before it ships.
        </Tile>
      </div>
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
    <Section>
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

const FEATURES = [
  { icon: IconRuns, t: "Runs & verdicts", b: "Start runs from the browser, watch them live, get a plain-English verdict with evidence." },
  { icon: IconScenarios, t: "Scenarios", b: "Every test explained: what the user says, what must happen, and how it did last time." },
  { icon: IconServer, t: "MCP audits", b: "A graded report card for each tool server, with the exact findings to fix." },
  { icon: IconShield, t: "Access control", b: "Full-access and read-only tokens, so the whole team can look without breaking anything." },
];

function FeatureTeaser() {
  return (
    <Section>
      <div className="grid items-center gap-12 lg:grid-cols-[0.9fr_1.1fr]">
        <div>
          <Heading eyebrow="The product" title={<>A dashboard, a CLI and a CI gate. <Serif>All on your machine.</Serif></>}
            lead="Run it next to your agent with one command. Your prompts, data and results never leave your infrastructure." className="mb-6" />
          <div className="flex flex-wrap items-center gap-5">
            <Cta href="/features/">Explore features</Cta>
            <More href="/compare/">How it compares</More>
          </div>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          {FEATURES.map(({ icon: Icon, t, b }) => (
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
