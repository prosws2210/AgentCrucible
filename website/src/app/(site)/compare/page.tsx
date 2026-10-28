import type { Metadata } from "next";
import { IconCheck, IconX } from "@/components/Icons";
import { Cta, CtaBand, Heading, PageHero, Section, Serif } from "@/components/site/kit";

export const metadata: Metadata = {
  title: "Compare · AgentCrucible",
  description: "How AgentCrucible differs from a typical eval script, from tracing tools and from unit tests, and when it is not the right tool.",
};

const ROWS: [string, string, string][] = [
  ["What gets graded", "The final reply", "Tool calls, data, files and the reply"],
  ["Attempts per test", "One", "Several, because agents are random"],
  ["“Did it get worse?”", "Eyeball two numbers", "Statistical verdict, or “needs N more runs”"],
  ["Test environment", "Shared, gets dirty", "Fresh database, repo and servers every time"],
  ["Third-party APIs", "Real calls, or hand-written stubs", "Mocked per scenario, every request recorded"],
  ["Attacks", "Rarely tested", "Prompt injection, destructive requests, data leaks"],
  ["LLM judges", "Trusted blindly", "Calibrated against your labels; demoted when unreliable"],
  ["Cost of a re-run", "Full model bill", "Free with --cache replay"],
  ["Framework lock-in", "SDK or tracing library", "None: environment variables"],
];

const OTHERS = [
  {
    t: "Unit and integration tests",
    good: "Deterministic code paths: parsers, tool implementations, API handlers.",
    gap: "They mock the model away, so they can't tell you whether the agent picks the right tool or asks before refunding.",
    together: "Keep them. AgentCrucible can run them as a check (state.command) after a coding agent's change.",
  },
  {
    t: "Tracing and observability",
    good: "Seeing what agents do in production, latency, cost, and debugging a specific incident.",
    gap: "They watch; they don't set up a clean world, replay the same situation many times, or block a pull request.",
    together: "Found a bad conversation in your traces? Write it up as a scenario so it can never regress unnoticed.",
  },
  {
    t: "Eval scripts and LLM-as-judge",
    good: "Quick quality checks on single responses: tone, relevance, formatting.",
    gap: "One attempt per case, a judge nobody validated, and no answer to “is this difference real?”",
    together: "Use judge.rubric for tone, but gate on state and trajectory checks, with a calibrated judge.",
  },
];

export default function Compare() {
  return (
    <>
      <PageHero eyebrow="Compare" title={<>Not another eval script. <Serif>A regression gate.</Serif></>}
        lead="Most agent evaluation reads the reply once and prints a score. AgentCrucible checks what the agent did, many times, in a clean world, and tells you whether a change is really better or worse." />

      <Section>
        <div className="card overflow-hidden">
          <div className="hidden grid-cols-[1fr_1fr_1.2fr] border-b border-line bg-panel-2/60 px-5 py-3 text-[12.5px] font-medium text-dim sm:grid">
            <span />
            <span>Typical eval script</span>
            <span className="text-ember">AgentCrucible</span>
          </div>
          {ROWS.map(([k, a, b]) => (
            <div key={k} className="grid gap-1.5 border-b border-line/60 px-5 py-3.5 text-[14px] last:border-0 sm:grid-cols-[1fr_1fr_1.2fr] sm:items-center sm:gap-3">
              <span className="font-medium">{k}</span>
              <span className="flex items-center gap-2 text-mute"><IconX className="h-3.5 w-3.5 shrink-0 text-dim" />{a}</span>
              <span className="flex items-center gap-2"><IconCheck className="h-3.5 w-3.5 shrink-0 text-ok" />{b}</span>
            </div>
          ))}
        </div>
      </Section>

      <Section className="border-t border-line/60">
        <Heading eyebrow="Alongside your other tools" title={<>What each kind of tool is <Serif>good at</Serif></>}
          lead="AgentCrucible replaces none of these. It answers a question they don't: “did this change make my agent worse?”" />
        <div className="grid gap-4 lg:grid-cols-3">
          {OTHERS.map((o) => (
            <div key={o.t} className="card flex flex-col p-6">
              <h3 className="text-[17px] font-semibold tracking-tight">{o.t}</h3>
              <Row label="Great for" tone="text-ok">{o.good}</Row>
              <Row label="Blind spot" tone="text-warn">{o.gap}</Row>
              <Row label="Together" tone="text-ember">{o.together}</Row>
            </div>
          ))}
        </div>
      </Section>

      <Section className="border-t border-line/60">
        <div className="grid gap-10 lg:grid-cols-2">
          <Heading eyebrow="Honestly" title={<>When it&apos;s <Serif>not</Serif> the right tool</>} className="mb-0"
            lead="Better to know before you spend an afternoon on it." />
          <ul className="space-y-3 text-[14.5px] text-mute">
            {[
              "A single prompt with no tools: a plain eval script is simpler.",
              "Agents that only work through a browser or a desktop GUI: there is no tool gateway for those yet.",
              "MySQL fixtures and Gemini or Bedrock native APIs aren't supported yet (Postgres, SQLite and OpenAI-compatible endpoints are).",
              "Remote MCP servers keep their own state between attempts; use staging or mocks for tools with side effects.",
            ].map((x) => (
              <li key={x} className="flex gap-3 rounded-xl border border-line bg-panel-2/40 px-4 py-3"><span className="text-dim">—</span>{x}</li>
            ))}
          </ul>
        </div>
        <div className="mt-10 flex flex-wrap gap-3">
          <Cta href="/how-it-works/">How it works</Cta>
          <Cta href="/faq/">Read the FAQ</Cta>
        </div>
      </Section>

      <CtaBand />
    </>
  );
}

function Row({ label, tone, children }: { label: string; tone: string; children: React.ReactNode }) {
  return (
    <div className="mt-4">
      <div className={`font-mono text-[11px] uppercase tracking-[0.12em] ${tone}`}>{label}</div>
      <p className="mt-1 text-[14px] leading-relaxed text-mute">{children}</p>
    </div>
  );
}
