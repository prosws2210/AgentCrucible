"use client";

import Link from "next/link";
import { useState } from "react";
import { CopyButton } from "./CopyButton";
import { Wizard } from "./Wizard";
import { CodeLines } from "./ui";
import { IconArrow, IconCheck, IconCode, IconImport } from "./Icons";

type Path = "import" | "manual";

const IMPORT_CMDS = `pip install "agentcrucible @ git+https://github.com/prosws2210/AgentCrucible"

# find every agent and tool, and draft their tests
crucible discover ./my-repo

# after review: write agent-tests/ and run each test once
crucible discover ./my-repo --apply`;

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
    <div className="mt-8 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="space-y-4">
        <ol className="space-y-3">
          <Step n={1} title="Point it at your repository" sub="A local folder or a Git URL. It reads the code without running it, skips secrets, and uses your local model by default." />
          <Step n={2} title="Review what it found" sub="A map of your agents, tools, databases and APIs, each with the file and line it came from, a few questions it couldn't answer, and a draft test for every tool." />
          <Step n={3} title="Approve" sub="It writes agent-tests/ with the config, adapters and scenarios for every agent, checks the connections and runs each test once. Nothing is written before this." />
        </ol>
        <div className="card p-5">
          <div className="text-[14px] font-semibold">In the dashboard</div>
          <p className="mt-1 text-[13.5px] text-mute">With AgentCrucible running (<code className="font-mono text-[12.5px]">docker compose up</code>), open the import screen and choose your folder.</p>
          <Link href="/dashboard/import/" className="mt-4 inline-flex items-center gap-2 rounded-full bg-fg px-5 py-2.5 text-[14px] font-semibold text-ink">
            Open Import codebase <IconArrow className="h-4 w-4" />
          </Link>
        </div>
      </div>

      <div className="lg:sticky lg:top-24">
        <div className="card overflow-hidden">
          <div className="flex items-center gap-2 border-b border-line px-4 py-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-ember/15 text-ember"><IconCode className="h-3.5 w-3.5" /></span>
            <span className="text-[14px] font-semibold">Or from the terminal</span>
            <span className="ml-auto"><CopyButton text={IMPORT_CMDS} /></span>
          </div>
          <pre className="code overflow-x-auto bg-panel-2 px-4 py-4 text-[12.5px] text-fg/90">
            <CodeLines code={IMPORT_CMDS} />
          </pre>
        </div>
        <ul className="mt-4 space-y-2 text-[13px] text-mute">
          {[
            "Works with LangGraph, OpenAI Agents SDK, PydanticAI, CrewAI, LlamaIndex, LangChain, MCP, plain model calls and web services.",
            "Destructive tools are mocked until you say otherwise.",
            "Keep it in sync later with crucible discover --check in CI.",
          ].map((t) => (
            <li key={t} className="flex gap-2"><IconCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-ember" />{t}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function Step({ n, title, sub }: { n: number; title: string; sub: string }) {
  return (
    <li className="card flex gap-4 p-4">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ember/15 font-mono text-[12.5px] text-ember">{n}</span>
      <div>
        <div className="text-[14.5px] font-semibold">{title}</div>
        <p className="mt-1 text-[13.5px] leading-relaxed text-mute">{sub}</p>
      </div>
    </li>
  );
}
