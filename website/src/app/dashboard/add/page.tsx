"use client";

import Link from "next/link";
import { useState } from "react";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { agentHref } from "@/components/app/agents";
import { useResource } from "@/components/app/hooks";
import { IconArrow, IconCode, IconImport, IconPlus } from "@/components/Icons";
import { Button, Card, CardHeader, Spinner } from "@/components/ui";
import { api, type NewAgent, type ProjectSummary } from "@/lib/api";

type Kind = NewAgent["kind"];
const KINDS: [Kind, string, string][] = [
  ["python", "Python function or agent", "A function that answers a message, or a LangGraph / OpenAI Agents / PydanticAI / CrewAI / LlamaIndex object"],
  ["typescript", "TypeScript or JavaScript", "An exported function or agent (Vercel AI SDK, Mastra, plain code)"],
  ["http", "A web service", "Any language: it takes a message over HTTP and answers"],
  ["command", "A command", "A program that already speaks AgentCrucible's one-JSON-line-per-turn protocol"],
];
const FRAMEWORKS: [string, string][] = [
  ["generic", "Plain function: takes the message, returns the reply"], ["langgraph", "LangGraph graph"],
  ["openai-agents", "OpenAI Agents SDK Agent"], ["pydantic-ai", "PydanticAI Agent"], ["crewai", "CrewAI Crew"],
  ["llamaindex", "LlamaIndex agent"],
];

export default function AddAgentsPage() {
  const { project } = useProject();
  const [open, setOpen] = useState(false);
  return (
    <>
      <PageHeader
        title="Add agents"
        sub="Agents live in projects. Import a codebase to find every agent in it at once, or add a single agent by hand. Both end up the same: an agent with an adapter, tests and results, in the Agents list."
      />
      <div className="grid gap-4 md:grid-cols-2">
        <Link href="/dashboard/import/" className="card group flex gap-4 p-5 transition-colors hover:border-ember/50">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-ember/15 text-ember"><IconImport /></span>
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2 text-[16px] font-semibold">
              Import a codebase
              <span className="rounded-full bg-ember/15 px-2 py-0.5 font-mono text-[10.5px] font-medium uppercase tracking-wider text-ember">Recommended</span>
            </span>
            <span className="mt-1 block text-[13.5px] leading-relaxed text-mute">
              Point it at a folder or Git URL. It reads the code without running it, finds every agent, tool, MCP server and
              database, drafts tests for each, and you review before anything is written. The result becomes its own project.
            </span>
            <span className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-ember">Start an import <IconArrow className="h-3.5 w-3.5 transition-transform group-hover:translate-x-0.5" /></span>
          </span>
        </Link>
        <button onClick={() => setOpen(true)} className={`card group flex gap-4 p-5 text-left transition-colors hover:border-ember/50 ${open ? "border-ember/50" : ""}`}>
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-white/[0.06] text-fg"><IconCode /></span>
          <span className="min-w-0">
            <span className="block text-[16px] font-semibold">Add one agent by hand</span>
            <span className="mt-1 block text-[13.5px] leading-relaxed text-mute">
              Tell us where the agent is and how to call it, and write its first test. Add it to <b className="text-fg">{project.project}</b> or
              to another codebase. AgentCrucible writes the adapter.
            </span>
            <span className="mt-3 inline-flex items-center gap-1.5 text-[13px] font-medium text-ember">{open ? "Fill in the form below" : "Open the form"} <IconArrow className="h-3.5 w-3.5" /></span>
          </span>
        </button>
      </div>

      {open && <AddAgentForm />}
      <AddExisting />
    </>
  );
}

function AddAgentForm() {
  const { project, canWrite, switchProject } = useProject();
  const roots = useResource<{ roots: string[]; suggestions: string[] }>("/api/discover/roots");
  const [where, setWhere] = useState<"here" | "other">("here");
  const [codebase, setCodebase] = useState("");
  const [kind, setKind] = useState<Kind>("python");
  const [f, setF] = useState<Required<Omit<NewAgent, "kind" | "codebase" | "factory">> & { factory: boolean }>({
    name: "", purpose: "", module: "", object: "", framework: "generic", factory: false, app_url: "http://localhost:8000",
    route: "POST /chat", command: "", task: "", must_call: "", must_not_call: "", reply_mentions: "",
  });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof f) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) =>
    setF((x) => ({ ...x, [k]: e.target.type === "checkbox" ? (e.target as HTMLInputElement).checked : e.target.value }));
  const home = project.codebase ?? project.root;

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const body: NewAgent = {
      name: f.name, kind, purpose: f.purpose, task: f.task, must_call: f.must_call, must_not_call: f.must_not_call,
      reply_mentions: f.reply_mentions, codebase: where === "other" ? codebase : null,
      ...(kind === "python" ? { module: f.module, object: f.object, framework: f.framework, factory: f.factory } : {}),
      ...(kind === "typescript" ? { module: f.module, object: f.object } : {}),
      ...(kind === "http" ? { app_url: f.app_url, route: f.route } : {}),
      ...(kind === "command" ? { command: f.command } : {}),
    };
    try {
      const r = await api<{ project: string; agent: string }>("/api/agents", { method: "POST", body: JSON.stringify(body) });
      switchProject(r.project, agentHref(r.agent));
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  const input = "w-full rounded-lg border border-line bg-panel-2 px-3 py-2 text-[13.5px] outline-none focus:border-ember/60";
  const mono = `${input} font-mono text-[12.5px]`;
  return (
    <form onSubmit={submit} className="card mt-5 overflow-hidden">
      <CardHeader title="Add one agent by hand" sub="Four short steps. Nothing in your agent's code changes; AgentCrucible writes a small adapter next to the tests." />
      <div className="space-y-7 p-5">
        <Step n={1} title="Which codebase is it in?">
          <div className="flex flex-wrap gap-2">
            <Chip on={where === "here"} onClick={() => setWhere("here")}>This project · {project.project}</Chip>
            <Chip on={where === "other"} onClick={() => setWhere("other")}>Another codebase</Chip>
          </div>
          {where === "here" ? (
            <p className="mt-2 text-[12.5px] text-dim">Code is looked up in <code className="break-all font-mono">{home}</code>.</p>
          ) : (
            <>
              <input list="codebases" value={codebase} onChange={(e) => setCodebase(e.target.value)} placeholder="/path/to/your/repo" className={`${mono} mt-3`} required />
              <datalist id="codebases">{(roots.data?.suggestions ?? []).map((s) => <option key={s} value={s} />)}</datalist>
              <p className="mt-1.5 text-[12px] text-dim">
                Tests go in its <code className="font-mono">agent-tests/</code> folder, as a new project (or the one already there).
                {roots.data && <> Allowed folders: <code className="font-mono">{roots.data.roots.join(", ")}</code>.</>}
              </p>
            </>
          )}
        </Step>

        <Step n={2} title="How do we reach it?">
          <div className="grid gap-2 sm:grid-cols-2">
            {KINDS.map(([k, t, d]) => (
              <button type="button" key={k} onClick={() => setKind(k)}
                className={`rounded-xl border p-3 text-left transition-colors ${kind === k ? "border-ember/60 bg-ember/[0.07]" : "border-line hover:border-white/20"}`}>
                <div className="text-[13.5px] font-medium">{t}</div>
                <div className="mt-0.5 text-[12px] leading-relaxed text-dim">{d}</div>
              </button>
            ))}
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2">
            {kind === "python" && <>
              <L label="Module" hint="Dotted path from the repo root (or src/)"><input value={f.module} onChange={set("module")} placeholder="app.agents.support" className={mono} required /></L>
              <L label="Function or object" hint="What to call or drive"><input value={f.object} onChange={set("object")} placeholder="run" className={mono} required /></L>
              <L label="What is it?"><select value={f.framework} onChange={set("framework")} className={input}>{FRAMEWORKS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select></L>
              {f.framework !== "generic" && (
                <label className="flex items-center gap-2 self-end pb-2 text-[13px] text-mute">
                  <input type="checkbox" checked={f.factory} onChange={set("factory")} className="accent-[#ff6b35]" /> It&apos;s a function that builds the agent
                </label>
              )}
            </>}
            {kind === "typescript" && <>
              <L label="File" hint="Relative to the repo root, without the extension"><input value={f.module} onChange={set("module")} placeholder="src/agent" className={mono} required /></L>
              <L label="Export" hint="The exported function or agent"><input value={f.object} onChange={set("object")} placeholder="runAgent" className={mono} required /></L>
            </>}
            {kind === "http" && <>
              <L label="Where it runs" hint="Start it yourself before a run"><input value={f.app_url} onChange={set("app_url")} className={mono} required /></L>
              <L label="Endpoint" hint="Takes {message} and answers; check the field names in the adapter"><input value={f.route} onChange={set("route")} className={mono} required /></L>
            </>}
            {kind === "command" && (
              <div className="sm:col-span-2">
                <L label="Command" hint="Run from the codebase folder"><input value={f.command} onChange={set("command")} placeholder="python agent_stdio.py" className={mono} required /></L>
              </div>
            )}
          </div>
        </Step>

        <Step n={3} title="Name it">
          <div className="grid gap-3 sm:grid-cols-2">
            <L label="Name"><input value={f.name} onChange={set("name")} placeholder="Support agent" className={input} required maxLength={80} /></L>
            <L label="What it does (optional)"><input value={f.purpose} onChange={set("purpose")} placeholder="Answers customer questions and handles refunds" className={input} /></L>
          </div>
        </Step>

        <Step n={4} title="Its first test" hint="A real request it gets. Leave a check empty to skip it; a judge model also grades the answer.">
          <L label="The user says"><textarea value={f.task} onChange={set("task")} rows={2} placeholder="Where is my order A-1001?" className={input} required /></L>
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <L label="Must use tool"><input value={f.must_call} onChange={set("must_call")} placeholder="find_order" className={mono} /></L>
            <L label="Must never use"><input value={f.must_not_call} onChange={set("must_not_call")} placeholder="delete_account" className={mono} /></L>
            <L label="Reply must mention"><input value={f.reply_mentions} onChange={set("reply_mentions")} placeholder="shipped" className={input} /></L>
          </div>
        </Step>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-panel/60 px-5 py-4">
        <p className="text-[12.5px] text-dim">Writes the adapter, a suite and this test. You land on the agent, ready to run it.</p>
        <div className="flex items-center gap-3">
          {error && <span role="alert" className="max-w-md text-[12.5px] text-bad">{error}</span>}
          <Button type="submit" disabled={busy || !canWrite} title={canWrite ? undefined : "Read-only access"}>{busy ? <><Spinner /> Adding…</> : <><IconPlus /> Add agent</>}</Button>
        </div>
      </div>
    </form>
  );
}

function AddExisting() {
  const { switchProject, canWrite } = useProject();
  const [path, setPath] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function add(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const p = await api<ProjectSummary>("/api/projects", { method: "POST", body: JSON.stringify({ path }) });
      switchProject(p.id, "/dashboard/");
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }
  return (
    <Card className="mt-5 p-5">
      <div className="text-[14px] font-semibold">Already have AgentCrucible tests somewhere?</div>
      <p className="mt-1 text-[13px] text-mute">Add a folder with a <code className="font-mono text-[12px]">crucible.yaml</code> (or a repo with <code className="font-mono text-[12px]">agent-tests/</code>) as a project.</p>
      <form onSubmit={add} className="mt-3 flex flex-col gap-2 sm:flex-row">
        <input value={path} onChange={(e) => setPath(e.target.value)} placeholder="/path/to/repo" required
          className="min-w-0 flex-1 rounded-lg border border-line bg-panel-2 px-3 py-2 font-mono text-[12.5px] outline-none focus:border-ember/60" />
        <Button type="submit" variant="secondary" disabled={busy || !canWrite}>{busy ? <Spinner /> : null} Add project</Button>
      </form>
      {error && <p role="alert" className="mt-2 text-[12.5px] text-bad">{error}</p>}
    </Card>
  );
}

function Step({ n, title, hint, children }: { n: number; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="flex gap-4">
      <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-ember/15 font-mono text-[12.5px] text-ember">{n}</span>
      <div className="min-w-0 flex-1">
        <h3 className="text-[14.5px] font-semibold">{title}</h3>
        {hint && <p className="mt-0.5 text-[12.5px] text-dim">{hint}</p>}
        <div className="mt-3">{children}</div>
      </div>
    </section>
  );
}

function L({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block min-w-0">
      <span className="mb-1 block text-[12.5px] font-medium text-mute">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11.5px] text-dim">{hint}</span>}
    </label>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={`max-w-full truncate rounded-full border px-3 py-1.5 text-[12.5px] transition-colors ${on ? "border-ember/60 bg-ember/10 text-fg" : "border-line text-mute hover:text-fg"}`}>
      {children}
    </button>
  );
}
