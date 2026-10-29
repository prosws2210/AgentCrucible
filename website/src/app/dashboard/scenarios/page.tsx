"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { useScenarios } from "@/components/app/hooks";
import { IconChat, IconGit, IconRuns, IconScenarios, IconShield } from "@/components/Icons";
import { Badge, Button, Card, Dots, Empty, Spinner } from "@/components/ui";
import { api, type Run, type Scenario } from "@/lib/api";
import { CHECK_HELP } from "@/lib/format";
import { GITHUB } from "@/lib/site";

const ENV: Record<string, { label: string; icon: React.ReactNode }> = {
  fixtures: { label: "fresh database", icon: null },
  workspace: { label: "fresh repo copy", icon: <IconGit className="h-3 w-3" /> },
  postgres: { label: "Postgres", icon: null },
  http_mocks: { label: "mocked HTTP API", icon: null },
  mocks: { label: "mocked tools", icon: null },
  inject: { label: "attack injected", icon: <IconShield className="h-3 w-3" /> },
  deny_tools: { label: "blocked tools", icon: <IconShield className="h-3 w-3" /> },
};

export default function ScenariosPage() {
  const { data, error } = useScenarios();
  const { project } = useProject();
  const [filter, setFilter] = useState("all");
  const [agent, setAgent] = useState("all");

  const mine = (data ?? []).filter((s) => agent === "all" || s.agent === agent);
  const suites = [...new Set(mine.map((s) => s.suite))];
  const shown = mine.filter((s) => filter === "all" || s.suite === filter || (filter === "failing" && s.latest && s.latest.passed < s.latest.n));

  return (
    <>
      <PageHeader
        title="Scenarios"
        sub={<>A scenario is one situation your agent must handle, with the checks that decide pass or fail. They live as YAML files in your repo, so they are reviewed like code. <a className="text-ember" href={`${GITHUB}/blob/main/docs/ADOPTION.md#4-write-scenarios`} target="_blank" rel="noreferrer">How to write one →</a></>}
      />
      {error && <Card className="p-5 text-[13px] text-bad">{error}</Card>}
      {!data ? (
        <div className="flex items-center justify-center gap-2 py-24 text-[13px] text-dim"><Spinner /> Loading scenarios…</div>
      ) : data.length === 0 ? (
        <Card><Empty icon={<IconScenarios />} title="No scenarios found">Add YAML files under the paths listed in your crucible.yaml suites.</Empty></Card>
      ) : (
        <>
          {project.agents.length > 1 && (
            <div className="mb-3 flex flex-wrap items-center gap-2">
              <span className="text-[12px] text-dim">Agent</span>
              {["all", ...project.agents.map((a) => a.name)].map((a) => (
                <button key={a} onClick={() => { setAgent(a); setFilter("all"); }}
                  className={`rounded-full border px-3 py-1.5 font-mono text-[12px] ${agent === a ? "border-ember/60 bg-ember/10" : "border-line text-mute hover:text-fg"}`}>
                  {a === "all" ? `all agents (${data.length})` : `${a} (${data.filter((s) => s.agent === a).length})`}
                </button>
              ))}
            </div>
          )}
          <div className="mb-4 flex flex-wrap gap-2">
            {["all", ...suites, "failing"].map((f) => (
              <button key={f} onClick={() => setFilter(f)}
                className={`rounded-full border px-3 py-1.5 text-[12.5px] ${filter === f ? "border-ember/60 bg-ember/10" : "border-line text-mute hover:text-fg"}`}>
                {f === "all" ? `All (${mine.length})` : f === "failing" ? "Failing" : `${f} (${mine.filter((s) => s.suite === f).length})`}
              </button>
            ))}
          </div>
          <div className="grid gap-4 lg:grid-cols-2">
            {shown.map((s) => <ScenarioCard key={s.id} s={s} />)}
          </div>
          {!shown.length && <Card><Empty title="Nothing here">No scenarios match this filter.</Empty></Card>}
        </>
      )}
    </>
  );
}

function ScenarioCard({ s }: { s: Scenario }) {
  const router = useRouter();
  const { canWrite, project } = useProject();
  const [busy, setBusy] = useState(false);
  async function run() {
    setBusy(true);
    try {
      const r = await api<Run>("/api/runs", { method: "POST", body: JSON.stringify({ scenarios: [s.id], runs: 3, label: `scenario: ${s.id}` }) });
      router.push(`/dashboard/run/?id=${r.id}`);
    } catch { setBusy(false); }
  }
  const status = s.latest ? (s.latest.passed === s.latest.n ? "ok" : s.latest.passed === 0 ? "bad" : "warn") : null;
  return (
    <Card className="flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-mono text-[13.5px] font-semibold">{s.id}</div>
          <div className="mt-0.5 text-[13px] text-mute">{s.description}</div>
        </div>
        {s.latest ? (
          <Link href={`/dashboard/run/?id=${s.latest.run_id}&scenario=${s.id}`} className="flex shrink-0 flex-col items-end gap-1" title={`Latest: ${s.latest.run_label || s.latest.run_id}`}>
            <Dots passed={s.latest.passed} n={s.latest.n} />
            <span className={`font-mono text-[11px] ${status === "ok" ? "text-ok" : status === "bad" ? "text-bad" : "text-warn"}`}>{s.latest.passed}/{s.latest.n} latest</span>
          </Link>
        ) : <Badge>not run yet</Badge>}
      </div>

      <div className="mt-4 rounded-lg border border-line bg-panel-2/60 px-3 py-2.5">
        <div className="mb-1 flex items-center gap-1.5 text-[11px] uppercase tracking-[0.12em] text-dim">
          <IconChat className="h-3 w-3" /> The user says{s.multi_turn ? " (then a simulated user continues)" : ""}
        </div>
        <p className="line-clamp-3 text-[13px] leading-relaxed text-fg/90">{s.task}</p>
      </div>

      <div className="mt-4">
        <div className="mb-1.5 text-[11px] uppercase tracking-[0.12em] text-dim">Passes only if</div>
        <ul className="space-y-1">
          {s.checks.map((c, i) => (
            <li key={i} className="flex items-baseline gap-2 text-[12.5px]">
              <span className={c.hard ? "text-ember" : "text-dim"}>•</span>
              <span className="text-fg/90">{CHECK_HELP[c.label] ?? c.label}</span>
              <code className="font-mono text-[10.5px] text-dim">{c.label}</code>
              {!c.hard && <span className="text-[11px] text-dim">(informational)</span>}
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 pt-5">
        <div className="flex flex-wrap gap-1.5">
          {project.agents.length > 1 && <Badge tone="ember">{s.agent}</Badge>}
          <Badge>{s.suite}</Badge>
          {s.environment.map((e) => <Badge key={e} tone={e === "inject" || e === "deny_tools" ? "warn" : "mute"}>{ENV[e]?.icon}{ENV[e]?.label ?? e}</Badge>)}
          {s.tags.filter((t) => t !== s.suite).map((t) => <Badge key={t}>#{t}</Badge>)}
        </div>
        <Button variant="secondary" onClick={run} disabled={busy || !canWrite} title={canWrite ? undefined : "Read-only access: sign in with the full-access token to start runs"}>{busy ? <Spinner /> : <IconRuns className="h-3.5 w-3.5" />} Run 3×</Button>
      </div>
    </Card>
  );
}
