"use client";

import Link from "next/link";
import { useState } from "react";
import { CopyButton } from "./CopyButton";
import { Wizard } from "./Wizard";
import { IconArrow, IconCheck, IconCode, IconImport } from "./Icons";

type Path = "import" | "manual";

const IMPORT_CMDS = `pip install git+https://github.com/prosws2210/AgentCrucible

# find every agent and tool, and draft their tests
crucible discover ./my-repo

# after review: write agent-tests/ and run each test once
crucible discover ./my-repo --apply

# see where every agent and MCP server is used
crucible graph ./my-repo`;

const FRAMEWORKS = ["LangGraph", "LangChain", "OpenAI Agents SDK", "CrewAI", "PydanticAI", "LlamaIndex", "Claude Agent SDK",
  "Google ADK", "Vercel AI SDK", "Mastra", "Spring AI", "LangChain4j", "Go", "MCP servers", "Raw tool loops"];

const STEPS = [
  { title: "Point it at your repository", sub: "A local folder or a Git URL. It reads the code without running it, skips secrets, and uses your local model by default." },
  { title: "Review what it found", sub: "Your agents, tools, databases and APIs, each with the file and line it came from, the few questions it couldn't answer, and a draft test for every tool." },
  { title: "Approve", sub: "It writes agent-tests/ with the config, adapters and scenarios, checks every connection and runs each test once. Nothing is written before this." },
  { title: "Keep the map", sub: <>A knowledge graph of the codebase lands next to the tests: every file, agent, tool and MCP server, and what uses what. <code className="whitespace-nowrap font-mono text-[12.5px] text-fg">crucible discover --check</code> keeps it honest in CI.</> },
];

/** The two ways in: import a whole codebase (every agent at once) or set up one agent by hand. */
export function StartPaths() {
  const [path, setPath] = useState<Path>("import");
  return (
    <>
      <div role="tablist" aria-label="How to start" className="mt-10 grid gap-3 sm:grid-cols-2">
        <PathCard
          on={path === "import"} onClick={() => setPath("import")} icon={<IconImport className="h-4 w-4" />}
          title="Import your codebase" tag="Recommended"
          sub="Point it at your repository. It finds every agent, tool and MCP server and drafts tests for all of them."
        />
        <PathCard
          on={path === "manual"} onClick={() => setPath("manual")} icon={<IconCode className="h-4 w-4" />}
          title="Set up one agent by hand"
          sub="Answer six questions and copy the config, an adapter and a first test. Good for a new or very small agent."
        />
      </div>
      {path === "import" ? <ImportPath /> : <Wizard />}
    </>
  );
}

function PathCard({ on, onClick, icon, title, tag, sub }: {
  on: boolean; onClick: () => void; icon: React.ReactNode; title: string; tag?: string; sub: string;
}) {
  return (
    <button role="tab" aria-selected={on} onClick={onClick}
      className={`card flex gap-3 p-4 text-left transition-colors ${on ? "border-ember/60 bg-ember/[0.06]" : "hover:border-white/20"}`}>
      <span className={`mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg ${on ? "bg-ember/15 text-ember" : "bg-panel-2 text-mute"}`}>{icon}</span>
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-2 text-[15px] font-semibold">
          {title}
          {tag && <span className="rounded-full bg-ember/15 px-2 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-wider text-ember">{tag}</span>}
        </span>
        <span className="mt-1 block text-[13.5px] leading-relaxed text-mute">{sub}</span>
      </span>
    </button>
  );
}

function ImportPath() {
  return (
    <div className="mt-8 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
      <div className="card p-5 sm:p-6">
        <div className="font-mono text-[11px] uppercase tracking-[0.16em] text-dim">How it works</div>
        <ol className="mt-4">
          {STEPS.map((s, i) => (
            <li key={s.title} className="relative flex gap-4 pb-6 last:pb-0">
              {i < STEPS.length - 1 && <span aria-hidden className="absolute bottom-0 left-[13px] top-8 w-px bg-line" />}
              <span className="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-ember/40 bg-ember/10 font-mono text-[12px] text-ember">{i + 1}</span>
              <div className="min-w-0 pt-0.5">
                <div className="text-[14.5px] font-semibold">{s.title}</div>
                <p className="mt-1 text-[13.5px] leading-relaxed text-mute">{s.sub}</p>
              </div>
            </li>
          ))}
        </ol>
        <div className="mt-6 flex flex-col gap-3 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
          <p className="text-[13px] text-mute">
            Running it with <code className="font-mono text-[12.5px] text-fg">docker compose up</code>? Import from the dashboard.
          </p>
          <Link href="/dashboard/import/" className="inline-flex shrink-0 items-center justify-center gap-2 rounded-full bg-fg px-5 py-2.5 text-[14px] font-semibold text-ink">
            Open Import codebase <IconArrow className="h-4 w-4" />
          </Link>
        </div>
      </div>

      <div className="space-y-4 lg:sticky lg:top-24">
        <div className="card overflow-hidden">
          <div className="flex items-center gap-3 border-b border-line px-4 py-3">
            <span aria-hidden className="flex gap-1.5"><i className="h-2.5 w-2.5 rounded-full bg-white/15" /><i className="h-2.5 w-2.5 rounded-full bg-white/15" /><i className="h-2.5 w-2.5 rounded-full bg-white/15" /></span>
            <span className="text-[13px] font-medium text-mute">Or from the terminal</span>
            <span className="ml-auto"><CopyButton text={IMPORT_CMDS} /></span>
          </div>
          <pre className="code overflow-x-auto bg-panel-2 px-4 py-4 text-[12.5px] leading-[1.7]">
            {IMPORT_CMDS.split("\n").map((line, i) =>
              !line ? <div key={i} className="h-2" /> :
              line.startsWith("#") ? <div key={i} className="text-dim">{line}</div> :
              <div key={i} className="whitespace-pre-wrap break-words pl-[2ch] -indent-[2ch] text-fg/90"><span className="select-none text-ember">$ </span>{line}</div>)}
          </pre>
        </div>
        <div className="card p-5">
          <div className="text-[14px] font-semibold">Finds agents built with</div>
          <ul className="mt-3 flex flex-wrap gap-1.5">
            {FRAMEWORKS.map((f) => <li key={f} className="rounded-full border border-line bg-panel-2 px-2.5 py-1 text-[12px] text-mute">{f}</li>)}
          </ul>
          <ul className="mt-4 space-y-2 border-t border-line pt-4 text-[13px] text-mute">
            {["Destructive tools are mocked until you say otherwise.", "Every finding links to its file and line; guesses become questions, not tests."].map((t) => (
              <li key={t} className="flex gap-2"><IconCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ember" />{t}</li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
