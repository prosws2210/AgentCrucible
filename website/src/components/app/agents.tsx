"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { api, type AgentRow, type Run } from "@/lib/api";
import { ago, pct } from "@/lib/format";
import { IconAgents, IconRuns } from "../Icons";
import { Badge, Button, Spinner } from "../ui";
import { useProject } from "./AppShell";
import { useResource } from "./hooks";

export const useAgents = () => useResource<AgentRow[]>("/api/agents");

export const ORIGIN: Record<AgentRow["origin"], { label: string; tone: "info" | "ok" | "mute" }> = {
  found: { label: "found in code", tone: "info" },
  hand: { label: "added by hand", tone: "ok" },
  config: { label: "from crucible.yaml", tone: "mute" },
};

export const FRAMEWORK: Record<string, string> = {
  generic: "plain code", langgraph: "LangGraph", "openai-agents": "OpenAI Agents SDK", "pydantic-ai": "PydanticAI",
  crewai: "CrewAI", llamaindex: "LlamaIndex", langchain: "LangChain", "vercel-ai": "Vercel AI SDK", mastra: "Mastra",
  "claude-agent-sdk": "Claude Agent SDK", autogen: "AutoGen", "google-adk": "Google ADK", "semantic-kernel": "Semantic Kernel",
  dspy: "DSPy", mcp: "MCP",
};

export const agentHref = (name: string) => `/dashboard/agent/?name=${encodeURIComponent(name)}`;

/** How the agent is doing in the latest results of its scenarios. */
export function health(a: AgentRow): { tone: "ok" | "warn" | "bad" | "mute"; label: string } {
  if (!a.scenarios) return { tone: "warn", label: "no tests yet" };
  if (!a.tested) return { tone: "mute", label: "not run yet" };
  if (a.failing === 0) return { tone: "ok", label: "all passing" };
  return { tone: a.failing === a.tested ? "bad" : "warn", label: `${a.failing} failing` };
}

/** Start a run of one agent's scenarios and open it. */
export function RunAgentButton({ name, k = 3, variant = "secondary", label }: { name: string; k?: number; variant?: "primary" | "secondary" | "ghost"; label?: string }) {
  const router = useRouter();
  const { canWrite } = useProject();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function run() {
    setBusy(true);
    setError(null);
    try {
      const r = await api<Run>("/api/runs", { method: "POST", body: JSON.stringify({ agent: name, runs: k, label: `agent: ${name}` }) });
      router.push(`/dashboard/run/?id=${r.id}`);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <span className="inline-flex flex-col items-start gap-1">
      <Button variant={variant} onClick={run} disabled={busy || !canWrite}
        title={canWrite ? `Runs every scenario of this agent ${k} times` : "Read-only access: sign in with the full-access token to start runs"}>
        {busy ? <Spinner /> : <IconRuns className="h-3.5 w-3.5" />} {label ?? `Run its tests ${k}×`}
      </Button>
      {error && <span className="text-[12px] text-bad">{error}</span>}
    </span>
  );
}

export function AgentCard({ a }: { a: AgentRow }) {
  const h = health(a);
  const rate = a.episodes ? a.passed / a.episodes : null;
  const risky = a.tools.filter((t) => t.effects.includes("destructive")).length;
  return (
    <div className="card flex flex-col p-5">
      <div className="flex items-start gap-3">
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-ember/12 text-ember"><IconAgents className="h-4.5 w-4.5" /></span>
        <div className="min-w-0 flex-1">
          <Link href={agentHref(a.name)} className="block truncate text-[15px] font-semibold hover:text-ember">{a.title}</Link>
          <div className="truncate font-mono text-[11.5px] text-dim">{a.name}{a.service ? ` · ${a.service}` : ""}</div>
        </div>
        <Badge tone={h.tone}>{h.label}</Badge>
      </div>
      {a.purpose && <p className="mt-3 line-clamp-2 text-[13px] leading-relaxed text-mute">{a.purpose}</p>}
      <div className="mt-3 flex flex-wrap gap-1.5">
        <Badge tone={ORIGIN[a.origin].tone}>{ORIGIN[a.origin].label}</Badge>
        {a.framework && <Badge>{FRAMEWORK[a.framework] ?? a.framework}</Badge>}
        {a.tools.length > 0 && <Badge>{a.tools.length} tools{risky ? ` · ${risky} destructive` : ""}</Badge>}
        {a.memory && <Badge>memory</Badge>}
      </div>

      <div className="mt-4 grid grid-cols-3 gap-2 rounded-lg border border-line bg-panel-2/60 p-3 text-center">
        <Metric value={a.scenarios} label="scenarios" />
        <Metric value={pct(rate)} label="pass rate" tone={rate == null ? undefined : rate >= 0.9 ? "ok" : rate >= 0.6 ? "warn" : "bad"} />
        <Metric value={a.last_tested ? ago(a.last_tested) : "never"} label="last tested" small />
      </div>
      {rate != null && (
        <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-panel-2" title={`${a.passed} of ${a.episodes} episodes passed in the latest results`}>
          <div className={`h-full rounded-full ${rate >= 0.9 ? "bg-ok" : rate >= 0.6 ? "bg-warn" : "bg-bad"}`} style={{ width: `${rate * 100}%` }} />
        </div>
      )}

      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4">
        <Button variant="ghost" href={agentHref(a.name)}>Details</Button>
        {a.scenarios > 0 && <RunAgentButton name={a.name} />}
      </div>
    </div>
  );
}

function Metric({ value, label, tone, small }: { value: React.ReactNode; label: string; tone?: "ok" | "warn" | "bad"; small?: boolean }) {
  const c = tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : tone === "bad" ? "text-bad" : "text-fg";
  return (
    <div className="min-w-0">
      <div className={`truncate font-semibold ${small ? "text-[13px] leading-[22px]" : "text-[17px]"} ${c}`}>{value}</div>
      <div className="text-[11px] text-dim">{label}</div>
    </div>
  );
}
