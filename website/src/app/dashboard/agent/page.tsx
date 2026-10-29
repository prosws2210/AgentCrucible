"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { FRAMEWORK, health, ORIGIN, RunAgentButton } from "@/components/app/agents";
import { useResource } from "@/components/app/hooks";
import { IconArrow, IconChat, IconScenarios } from "@/components/Icons";
import { Badge, Button, Card, CardHeader, Dots, Empty, PassRate, Spinner, Stat } from "@/components/ui";
import { api, type AgentDetail, type Effect } from "@/lib/api";
import { ago, CHECK_HELP, pct, when } from "@/lib/format";

const EFFECT_TONE: Record<Effect, "ok" | "warn" | "bad" | "info" | "mute"> = {
  "read-only": "ok", "writes data": "warn", destructive: "bad", "external call": "info", "reads untrusted text": "warn",
};

const STRATEGY: Record<string, string> = {
  code: "Imported and called in-process through an adapter",
  http: "Messages forwarded to its web endpoint",
  stdio: "Started as a program; one message per line",
  manual: "Adapter scaffold to finish by hand",
};

export default function AgentPage() {
  return (
    <Suspense>
      <Agent />
    </Suspense>
  );
}

function Agent() {
  const name = useSearchParams().get("name") ?? "";
  const { project } = useProject();
  const { data: a, error } = useResource<AgentDetail>(name ? `/api/agents/${encodeURIComponent(name)}` : null);

  if (error) {
    return (
      <Card>
        <Empty title="Agent not found" action={<Button href="/dashboard/agents/">All agents</Button>}>
          {error}. It may belong to another project than <b className="text-fg">{project.project}</b>; switch projects in the sidebar.
        </Empty>
      </Card>
    );
  }
  if (!a) return <div className="flex items-center justify-center gap-2 py-24 text-[13px] text-dim"><Spinner /> Loading agent…</div>;

  const h = health(a);
  const rate = a.episodes ? a.passed / a.episodes : null;
  return (
    <>
      <div className="mb-2 text-[12.5px] text-dim">
        <Link href="/dashboard/agents/" className="hover:text-fg">Agents</Link> <span className="mx-1">/</span> {a.title}
      </div>
      <PageHeader
        title={a.title}
        sub={<>
          <span className="font-mono text-[12.5px]">{a.name}</span> · {ORIGIN[a.origin].label}
          {a.framework ? <> · {FRAMEWORK[a.framework] ?? a.framework}</> : null}
          {a.purpose ? <><br />{a.purpose}</> : null}
        </>}
        actions={a.scenarios > 0 && <><RunAgentButton name={a.name} k={1} variant="secondary" label="Quick check (1×)" /><RunAgentButton name={a.name} variant="primary" /></>}
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Scenarios" value={a.scenarios} sub={a.suites.length ? `suite${a.suites.length === 1 ? "" : "s"}: ${a.suites.join(", ")}` : "no suite"} />
        <Stat label="Pass rate · latest results" value={pct(rate)} sub={a.episodes ? `${a.passed} of ${a.episodes} episodes` : "run its tests to see"}
          tone={rate == null ? undefined : rate >= 0.9 ? "ok" : rate >= 0.6 ? "warn" : "bad"} />
        <Stat label="Status" value={<span className="text-[20px]">{h.label}</span>} tone={h.tone === "mute" ? undefined : h.tone} sub={`${a.tested} of ${a.scenarios} scenarios have results`} />
        <Stat label="Last tested" value={<span className="text-[20px]">{a.last_tested ? ago(a.last_tested) : "never"}</span>} sub={a.last_tested ? when(a.last_tested) : "no finished run yet"} />
      </div>

      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[1.5fr_1fr]">
        <Card>
          <CardHeader title={`Tests (${a.scenario_list.length})`} sub="Each one is a situation this agent must handle, with the checks that decide pass or fail." />
          {a.scenario_list.length === 0 ? (
            <Empty icon={<IconScenarios />} title="No tests for this agent yet">
              Add YAML files to <code className="font-mono text-[12.5px]">scenarios/{a.name}/</code> in the project folder, or re-import the codebase to draft them.
            </Empty>
          ) : (
            <ul className="divide-y divide-line/70">
              {a.scenario_list.map((s) => (
                <li key={s.id} className="px-5 py-4">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="break-all font-mono text-[12.5px] font-semibold">{s.id}</div>
                      {s.description && <div className="text-[12.5px] text-mute">{s.description}</div>}
                    </div>
                    {s.latest ? (
                      <Link href={`/dashboard/run/?id=${s.latest.run_id}&scenario=${s.id}`} className="flex shrink-0 flex-col items-end gap-1" title="Open the latest result">
                        <Dots passed={s.latest.passed} n={s.latest.n} />
                        <span className={`font-mono text-[11px] ${s.latest.passed === s.latest.n ? "text-ok" : s.latest.passed === 0 ? "text-bad" : "text-warn"}`}>{s.latest.passed}/{s.latest.n} latest</span>
                      </Link>
                    ) : <Badge>not run yet</Badge>}
                  </div>
                  <p className="mt-2 flex gap-1.5 text-[12.5px] text-fg/85"><IconChat className="mt-0.5 h-3 w-3 shrink-0 text-dim" /><span className="line-clamp-2">{s.task}</span></p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {s.checks.map((c, i) => (
                      <span key={i} title={CHECK_HELP[c.label] ?? c.label}
                        className={`rounded-md px-1.5 py-0.5 font-mono text-[10.5px] ${c.hard ? "bg-ember/10 text-fg/85" : "bg-white/5 text-dim"}`}>{c.label}</span>
                    ))}
                    {s.multi_turn && <Badge>multi-turn</Badge>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <div className="space-y-5">
          <Card>
            <CardHeader title="How it's connected" sub={a.connection ? STRATEGY[a.connection.strategy] ?? a.connection.strategy : a.transport === "http" ? "A web service AgentCrucible talks to" : "Started by AgentCrucible for every test"} />
            <dl className="space-y-3 px-5 py-4 text-[12.5px]">
              {a.connection?.why && <p className="text-mute">{a.connection.why}</p>}
              <Row k="Transport" v={a.transport ?? "–"} />
              {a.command && <Row k="Command" v={<code className="break-all font-mono text-[12px]">{a.command}</code>} />}
              {a.url && <Row k="URL" v={<code className="break-all font-mono text-[12px]">{a.url}</code>} />}
              {a.cwd && <Row k="Runs in" v={<code className="break-all font-mono text-[12px]">{a.cwd}</code>} />}
              {a.connection?.adapter_file && <Row k="Adapter" v={<code className="break-all font-mono text-[12px]">{a.connection.adapter_file}</code>} />}
              {Object.keys(a.env).length > 0 && (
                <Row k="Environment" v={<span className="flex flex-col gap-0.5">{Object.entries(a.env).map(([k, v]) => <code key={k} className="break-all font-mono text-[11.5px]">{k}={v}</code>)}</span>} />
              )}
              {a.connection && a.connection.env_needed.length > 0 && (
                <Row k="You set" v={<span className="flex flex-wrap gap-1">{a.connection.env_needed.map((e) => <Badge key={e} tone="warn">{e}</Badge>)}</span>} />
              )}
            </dl>
            {a.connection && a.connection.warnings.length > 0 && (
              <ul className="space-y-1.5 border-t border-line px-5 py-3 text-[12.5px] text-warn">
                {a.connection.warnings.map((w, i) => <li key={i}>• {w}</li>)}
              </ul>
            )}
          </Card>

          {(a.tools.length > 0 || a.model || a.memory || a.subagents.length > 0 || a.mcp_servers.length > 0) && (
            <Card>
              <CardHeader title="What it uses" sub="Found in its code by the import." />
              <dl className="space-y-3 px-5 py-4 text-[12.5px]">
                {a.model && <Row k="Model in code" v={<code className="font-mono">{a.model}</code>} />}
                {a.memory && <Row k="Memory" v={a.memory} />}
                {a.subagents.length > 0 && <Row k="Sub-agents" v={a.subagents.join(", ")} />}
                {a.mcp_servers.length > 0 && <Row k="MCP servers" v={a.mcp_servers.join(", ")} />}
              </dl>
              {a.tools.length > 0 && (
                <ul className="divide-y divide-line/70 border-t border-line">
                  {a.tools.map((t) => (
                    <li key={t.name} className="px-5 py-2.5">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <span className="font-mono text-[12.5px]">{t.name}</span>
                        {t.effects.map((e) => <Badge key={e} tone={EFFECT_TONE[e]}>{e}</Badge>)}
                        {(t.mock ?? t.effects.includes("destructive")) && <Badge>mocked in tests</Badge>}
                      </div>
                      {t.description && <div className="mt-0.5 line-clamp-2 text-[12px] text-dim">{t.description}</div>}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          )}

          <Card>
            <CardHeader title="Recent runs" sub="Runs that included this agent's tests; the numbers are for this agent only." />
            {a.runs.length === 0 ? (
              <div className="px-5 py-6 text-[13px] text-dim">No runs yet.</div>
            ) : (
              <ul className="divide-y divide-line/70">
                {a.runs.map((r) => (
                  <li key={r.id}>
                    <Link href={`/dashboard/run/?id=${r.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-white/[0.03]">
                      <div className="min-w-0">
                        <div className="truncate text-[13px] font-medium">{r.label || <span className="text-mute">unlabeled run</span>}</div>
                        <div className="truncate font-mono text-[11px] text-dim">{when(r.created_at)} · {r.model}{r.agent ? "" : " · whole project"}</div>
                      </div>
                      {r.n ? <PassRate value={(r.passed ?? 0) / r.n} /> : <Badge tone={r.status === "failed" ? "bad" : "info"}>{r.status}</Badge>}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            <div className="border-t border-line px-5 py-3">
              <Button variant="ghost" href="/dashboard/runs/">All runs <IconArrow /></Button>
            </div>
          </Card>

          {project.agents.length > 1 && <RemoveAgent a={a} />}
        </div>
      </div>
    </>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_minmax(0,1fr)] gap-3">
      <dt className="text-dim">{k}</dt>
      <dd className="min-w-0 text-fg/90">{v}</dd>
    </div>
  );
}

function RemoveAgent({ a }: { a: AgentDetail }) {
  const { project, canWrite, switchProject } = useProject();
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (!canWrite) return null;
  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/agents/${encodeURIComponent(a.name)}`, { method: "DELETE" });
      switchProject(project.id, "/dashboard/agents/");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  const what = a.origin === "found"
    ? "It's left out of the tests; importing the codebase again offers it back."
    : "Its adapter and the tests written for it are deleted, unless you edited them.";
  return (
    <Card className="p-5">
      <div className="text-[13.5px] font-semibold">Remove this agent</div>
      <p className="mt-1 text-[12.5px] text-mute">{what} Past runs stay in the history.</p>
      <div className="mt-3 flex flex-wrap items-center gap-2">
        {confirm ? (
          <>
            <Button variant="secondary" onClick={remove} disabled={busy} className="!border-bad/50 !text-bad">{busy ? <Spinner /> : null} Remove {a.name}</Button>
            <Button variant="ghost" onClick={() => setConfirm(false)}>Keep it</Button>
          </>
        ) : <Button variant="ghost" onClick={() => setConfirm(true)} className="!px-0 !text-bad">Remove agent…</Button>}
      </div>
      {error && <p role="alert" className="mt-2 text-[12.5px] text-bad">{error}</p>}
    </Card>
  );
}
