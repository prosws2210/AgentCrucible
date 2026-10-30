"use client";

import { useMemo, useState } from "react";
import {
  adapterFile, commands, crucibleYaml, DEFAULTS, PROVIDERS, scenarioYaml,
  type AgentKind, type Answers, type LlmApi, type Provider, type StateKind,
} from "@/lib/wizard";
import { CopyButton } from "./CopyButton";
import { CodeLines } from "./ui";
import { IconCheck, IconCode, IconGit, IconPlus, IconServer, IconX } from "./Icons";

export function Wizard() {
  const [a, setA] = useState<Answers>(DEFAULTS);
  const set = <K extends keyof Answers>(k: K, v: Answers[K]) => setA((x) => ({ ...x, [k]: v }));

  const files = useMemo(() => {
    const adapter = adapterFile(a);
    return [
      { name: "crucible.yaml", code: crucibleYaml(a), note: "Project config: how to reach your agent, models and MCP servers." },
      { name: adapter.name, code: adapter.code, note: adapter.note },
      { name: "scenarios/smoke/first-scenario.yaml", code: scenarioYaml(a), note: "Your first test. Duplicate it for every real situation you care about." },
      { name: "terminal", code: commands(a), note: "Run these in the folder with crucible.yaml." },
    ];
  }, [a]);
  const [tab, setTab] = useState(0);
  const file = files[tab];

  return (
    <div className="mt-10 grid items-start gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
      <div className="space-y-4">
        <Q n={1} title="How does your agent run?" hint="Pick the closest. Nothing about your agent's logic changes.">
          <Choices<AgentKind>
            value={a.agent}
            onChange={(v) => set("agent", v)}
            options={[
              ["python", "Python script or CLI", "LangGraph, CrewAI, OpenAI Agents SDK, plain Python…"],
              ["node", "Node.js script or CLI", "Vercel AI SDK, Mastra, LangChain.js, plain TS…"],
              ["http", "A web service", "Any language. You POST a message, it answers."],
            ]}
          />
        </Q>

        <Q n={2} title="Which model API does it call?">
          <Choices<LlmApi>
            value={a.api}
            onChange={(v) => setA((x) => ({ ...x, api: v, model: PROVIDERS[x.provider].model[v] }))}
            options={[
              ["openai", "OpenAI-compatible", "OpenAI SDK, LiteLLM, most frameworks"],
              ["anthropic", "Anthropic Messages", "Claude SDK, streaming and tool use"],
            ]}
          />
        </Q>

        <Q n={3} title="Which models should tests use?" hint={PROVIDERS[a.provider].note}>
          <div className="flex flex-wrap gap-2">
            {(Object.keys(PROVIDERS) as Provider[])
              .filter((p) => (a.api === "anthropic" ? ["ollama", "anthropic"].includes(p) : p !== "anthropic"))
              .map((p) => (
                <Pill key={p} on={a.provider === p} onClick={() => setA((x) => ({ ...x, provider: p, model: PROVIDERS[p].model[x.api] }))}>
                  {PROVIDERS[p].label}
                </Pill>
              ))}
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <Input label="Model" value={a.model} onChange={(v) => set("model", v)} />
            {a.provider === "custom" && <Input label="Base URL" value={a.customUrl} onChange={(v) => set("customUrl", v)} />}
          </div>
        </Q>

        <Q n={4} title="Which MCP servers does it use?" hint="The command that starts each server over stdio (a fresh copy starts for every test), or the URL of a server that's already running.">
          <div className="space-y-2">
            {a.servers.map((s, i) => (
              <div key={i} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-2 sm:grid-cols-[9rem_minmax(0,1fr)_auto]">
                <input aria-label="Server name" value={s.name} onChange={(e) => set("servers", a.servers.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                  placeholder="name" className={`${field} w-full min-w-0 font-mono text-[12.5px]`} />
                <input aria-label="Server command or URL" value={s.command} onChange={(e) => set("servers", a.servers.map((x, j) => (j === i ? { ...x, command: e.target.value } : x)))}
                  placeholder="command or https://…/mcp" className={`${field} order-last col-span-2 w-full min-w-0 font-mono text-[12.5px] sm:order-none sm:col-span-1`} />
                <button onClick={() => set("servers", a.servers.filter((_, j) => j !== i))} className="flex h-9 w-9 items-center justify-center rounded-lg text-mute hover:bg-white/[0.04] hover:text-bad" aria-label="Remove server">
                  <IconX />
                </button>
              </div>
            ))}
            <button onClick={() => set("servers", [...a.servers, { name: "", command: "" }])} className="flex items-center gap-1.5 text-[13px] text-ember">
              <IconPlus className="h-3.5 w-3.5" /> Add a server
            </button>
          </div>
        </Q>

        <Q n={5} title="Does it change anything you can check?" hint="Checking the result, not just the reply, is how you catch an agent that says “done” but did nothing.">
          <Choices<StateKind>
            value={a.state}
            onChange={(v) => set("state", v)}
            options={[
              ["none", "Just conversation", "Grade replies and tool calls"],
              ["sqlite", "A database", "Fresh SQLite from a seed per test, query it after"],
              ["repo", "A code repository", "Fresh repo copy per test, run tests and diff after"],
            ]}
          />
        </Q>

        <Q n={6} title="Your first test" hint="Take a real request your agent gets. Leave a field empty to skip that check.">
          <Input label="The user says" value={a.task} onChange={(v) => set("task", v)} />
          <div className="mt-3 grid gap-3 sm:grid-cols-3">
            <Input label="Must use tool" placeholder="e.g. find_order" value={a.mustCall} onChange={(v) => set("mustCall", v)} />
            <Input label="Must never use" placeholder="e.g. delete_account" value={a.mustNotCall} onChange={(v) => set("mustNotCall", v)} />
            <Input label="Reply must mention" placeholder="e.g. refund" value={a.replyMentions} onChange={(v) => set("replyMentions", v)} />
          </div>
        </Q>
      </div>

      {/* generated files */}
      <div className="lg:sticky lg:top-24">
        <div className="card overflow-hidden">
          <div className="flex items-center gap-2 border-b border-line px-4 py-3">
            <span className="flex h-6 w-6 items-center justify-center rounded-md bg-ember/15 text-ember"><IconCode className="h-3.5 w-3.5" /></span>
            <span className="text-[14px] font-semibold">Your setup</span>
            <span className="ml-auto text-[12px] text-dim">updates as you answer</span>
          </div>
          <div className="flex gap-1 overflow-x-auto border-b border-line px-2 pt-2">
            {files.map((f, i) => (
              <button key={f.name} onClick={() => setTab(i)}
                className={`shrink-0 rounded-t-lg px-3 py-2 font-mono text-[12px] ${tab === i ? "bg-panel-2 text-fg" : "text-dim hover:text-mute"}`}>
                {f.name.split("/").pop()}
              </button>
            ))}
          </div>
          <div className="flex items-center justify-between gap-3 bg-panel-2 px-4 py-2.5">
            <span className="text-[12.5px] text-mute">{file.note}</span>
            <div className="flex shrink-0 gap-1.5">
              {file.name !== "terminal" && (
                <button onClick={() => download(file.name.split("/").pop()!, file.code)} className="rounded-md border border-line bg-panel px-2 py-1 font-mono text-[11px] text-mute hover:text-fg">
                  download
                </button>
              )}
              <CopyButton text={file.code} />
            </div>
          </div>
          <pre className="code max-h-[560px] overflow-y-auto bg-panel-2 px-4 pb-4 text-[12.5px] text-fg/90">
            <CodeLines code={file.code} />
          </pre>
        </div>
        <ul className="mt-4 grid gap-2 text-[12.5px] text-mute sm:grid-cols-3">
          <Li icon={<IconServer className="h-3.5 w-3.5" />}>Runs on your machine. Nothing leaves it.</Li>
          <Li icon={<IconGit className="h-3.5 w-3.5" />}>Config and tests live in your repo.</Li>
          <Li icon={<IconCheck className="h-3.5 w-3.5" />}>Source available (FSL-1.1): free for your own team.</Li>
        </ul>
      </div>
    </div>
  );
}

// no width here: callers size the box (a `w-full` in here would override their widths)
const field = "rounded-lg border border-line bg-panel-2 px-3 py-2 text-[13.5px] outline-none focus:border-ember/60";

function download(name: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/plain" }));
  const el = document.createElement("a");
  el.href = url;
  el.download = name;
  el.click();
  URL.revokeObjectURL(url);
}

function Q({ n, title, hint, children }: { n: number; title: string; hint?: string; children: React.ReactNode }) {
  return (
    <section className="card p-5">
      <div className="flex items-start gap-3">
        <span className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-ember/15 font-mono text-[11.5px] text-ember">{n}</span>
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold">{title}</h2>
          {hint && <p className="mt-0.5 text-[12.5px] text-mute">{hint}</p>}
          <div className="mt-3.5">{children}</div>
        </div>
      </div>
    </section>
  );
}

function Choices<T extends string>({ value, onChange, options }: { value: T; onChange: (v: T) => void; options: [T, string, string][] }) {
  return (
    <div className={`grid gap-2 ${options.length === 2 ? "sm:grid-cols-2" : ""}`}>
      {options.map(([v, title, sub]) => (
        <button key={v} onClick={() => onChange(v)}
          className={`rounded-xl border p-3 text-left transition-colors ${value === v ? "border-ember/60 bg-ember/[0.07]" : "border-line hover:border-white/20"}`}>
          <div className="flex items-center justify-between gap-2">
            <span className="text-[13.5px] font-medium">{title}</span>
            <span className={`h-3.5 w-3.5 shrink-0 rounded-full border ${value === v ? "border-ember bg-ember shadow-[inset_0_0_0_2px_var(--color-ink)]" : "border-line"}`} />
          </div>
          <div className="mt-1 text-[12px] leading-snug text-dim">{sub}</div>
        </button>
      ))}
    </div>
  );
}

function Pill({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick} className={`rounded-full border px-3 py-1.5 text-[12.5px] ${on ? "border-ember/60 bg-ember/10 text-fg" : "border-line text-mute hover:text-fg"}`}>
      {children}
    </button>
  );
}

function Input({ label, value, onChange, placeholder }: { label: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] text-mute">{label}</span>
      <input value={value} placeholder={placeholder} onChange={(e) => onChange(e.target.value)} className={`${field} w-full`} />
    </label>
  );
}

function Li({ icon, children }: { icon: React.ReactNode; children: React.ReactNode }) {
  return (
    <li className="flex items-center gap-2 rounded-lg border border-line px-3 py-2">
      <span className="text-ember">{icon}</span>
      {children}
    </li>
  );
}
