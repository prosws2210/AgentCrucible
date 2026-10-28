"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { useAudits, useResource, useRuns, useScenarios } from "@/components/app/hooks";
import { TrendChart } from "@/components/app/TrendChart";
import { IconArrow, IconCheck, IconPlus, IconX } from "@/components/Icons";
import { Badge, Button, Card, CardHeader, Dots, Empty, PassRate, Spinner, Stat } from "@/components/ui";
import { api, type Doctor, type Run } from "@/lib/api";
import { Grade, RunStatus } from "@/components/app/bits";
import { ago, pct, signedPts, when } from "@/lib/format";
import { GITHUB } from "@/lib/site";

export default function OverviewPage() {
  const { project, canWrite } = useProject();
  const runs = useRuns();
  const scenarios = useScenarios();
  const audits = useAudits();
  const nScenarios = Object.values(project.suites).reduce((n, s) => n + s.scenarios.length, 0);

  if (!runs.data) return <Loading />;
  if (runs.data.length === 0) return <Welcome nScenarios={nScenarios} />;

  const all = runs.data;
  const done = all.filter((r) => r.status === "done");
  const active = all.find((r) => r.status === "running" || r.status === "queued");
  const latest = done[0];
  const previous = done[1];
  const failing = (scenarios.data ?? []).filter((s) => s.latest && s.latest.passed < s.latest.n)
    .sort((a, b) => a.latest!.passed / a.latest!.n - b.latest!.passed / b.latest!.n);
  const trend = [...done].reverse().slice(-20).map((r) => ({
    id: r.id, label: r.label, date: when(r.created_at), value: r.pass_at_1 ?? 0, gate: r.gate,
  }));

  return (
    <>
      <PageHeader
        title={project.project}
        sub={`${nScenarios} scenarios · ${project.mcp_servers.length} MCP server${project.mcp_servers.length === 1 ? "" : "s"} · model ${project.model}`}
        actions={canWrite && <Button href="/dashboard/runs/?new=1"><IconPlus /> New run</Button>}
      />

      {active && <ActiveRun run={active} />}
      {latest && <LatestSummary run={latest} previous={previous} />}

      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Pass rate · latest run" value={pct(latest?.pass_at_1)}
          sub={previous && latest ? `${signedPts((latest.pass_at_1 ?? 0) - (previous.pass_at_1 ?? 0))} vs previous` : "first finished run"}
          tone={latest?.pass_at_1 == null ? undefined : latest.pass_at_1 >= 0.9 ? "ok" : latest.pass_at_1 >= 0.6 ? "warn" : "bad"} />
        <Stat label={latest?.k === 1 ? "Scenarios passed · latest run" : `Reliability · all ${latest?.k ?? "k"} attempts pass`} value={pct(latest?.pass_pow_k)}
          sub={latest?.k === 1 ? "use 3+ attempts to measure reliability" : "share of scenarios that never fail"} />
        <Stat label="Scenarios failing" value={scenarios.data ? failing.length : "–"} sub={`of ${nScenarios} in the latest results`} tone={failing.length ? "bad" : "ok"} />
        <Stat label="Runs" value={all.length} sub={latest ? `last finished ${ago(latest.finished_at ?? latest.created_at)}` : "none finished yet"} />
      </div>

      <div className="mt-5 grid items-start gap-5 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader title="Pass rate over runs" sub="Share of episodes that passed every hard check. Click a point to open the run." />
          <div className="px-3 py-4">
            {trend.length ? <TrendChartLink points={trend} /> : <div className="py-10 text-center text-[13px] text-dim">No finished runs yet.</div>}
          </div>
        </Card>
        <Card>
          <CardHeader title="Needs attention" sub="Scenarios that failed at least once in their latest run" />
          {failing.length === 0 ? (
            <Empty icon={<IconCheck />} title="Nothing failing">Every scenario passed all attempts in its latest run.</Empty>
          ) : (
            <ul className="divide-y divide-line/70">
              {failing.slice(0, 6).map((s) => (
                <li key={s.id}>
                  <Link href={`/dashboard/run/?id=${s.latest!.run_id}&scenario=${s.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-white/[0.03]">
                    <div className="min-w-0">
                      <div className="truncate font-mono text-[12.5px]">{s.id}</div>
                      <div className="truncate text-[12px] text-dim">{s.description}</div>
                    </div>
                    <div className="flex shrink-0 items-center gap-2.5">
                      <Dots passed={s.latest!.passed} n={s.latest!.n} />
                      <span className="font-mono text-[12px] text-mute">{s.latest!.passed}/{s.latest!.n}</span>
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>

      <div className="mt-5 grid gap-5 lg:grid-cols-[1.6fr_1fr]">
        <Card>
          <CardHeader title="Recent runs" action={<Button variant="ghost" href="/dashboard/runs/">All runs <IconArrow /></Button>} />
          <ul className="divide-y divide-line/70">
            {all.slice(0, 5).map((r) => <RunRow key={r.id} r={r} />)}
          </ul>
        </Card>
        <Card>
          <CardHeader title="MCP servers" action={<Button variant="ghost" href="/dashboard/servers/">Audit <IconArrow /></Button>} />
          <ul className="divide-y divide-line/70">
            {project.mcp_servers.map((name) => {
              const a = (audits.data ?? []).find((x) => x.server === name);
              return (
                <li key={name} className="flex items-center justify-between px-5 py-3">
                  <div>
                    <div className="font-mono text-[13px]">{name}</div>
                    <div className="text-[12px] text-dim">{a ? `audited ${ago(a.created_at)}` : "not audited yet"}</div>
                  </div>
                  {a ? <Grade grade={a.grade} score={a.overall} /> : <Badge>no grade</Badge>}
                </li>
              );
            })}
          </ul>
        </Card>
      </div>
    </>
  );
}

function TrendChartLink({ points }: { points: Parameters<typeof TrendChart>[0]["points"] }) {
  const router = useRouter();
  return <TrendChart points={points} onSelect={(id) => router.push(`/dashboard/run/?id=${id}`)} />;
}

function RunRow({ r }: { r: Run }) {
  return (
    <li>
      <Link href={`/dashboard/run/?id=${r.id}`} className="flex items-center justify-between gap-3 px-5 py-3 hover:bg-white/[0.03]">
        <div className="min-w-0">
          <div className="truncate text-[13.5px] font-medium">{r.label || <span className="text-mute">unlabeled run</span>}</div>
          <div className="truncate font-mono text-[11.5px] text-dim">{when(r.created_at)} · {r.model}{r.suite ? ` · ${r.suite}` : ""}</div>
        </div>
        <div className="flex shrink-0 items-center gap-3">
          <PassRate value={r.pass_at_1} />
          <RunStatus r={r} />
        </div>
      </Link>
    </li>
  );
}

function ActiveRun({ run }: { run: Run }) {
  const p = run.progress;
  return (
    <Link href={`/dashboard/run/?id=${run.id}`} className="card mb-5 block p-5 transition-colors hover:border-info/40">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <Spinner className="h-4 w-4 text-info" />
          <div>
            <div className="text-[14px] font-semibold">Running “{run.label || "unlabeled"}”</div>
            <div className="text-[12.5px] text-mute">
              {p ? `${p.done} of ${p.total} episodes done${p.failed ? ` · ${p.failed} failed so far` : ""}` : "starting…"}
            </div>
          </div>
        </div>
        <span className="text-[13px] text-info">Watch live →</span>
      </div>
      {p && (
        <div className="mt-4 h-1.5 overflow-hidden rounded-full bg-panel-2">
          <div className="h-full rounded-full bg-info transition-all" style={{ width: `${(100 * p.done) / p.total}%` }} />
        </div>
      )}
    </Link>
  );
}

function LatestSummary({ run, previous }: { run: Run; previous?: Run }) {
  // without a baseline there is no gate verdict, only the plain outcome
  const passed = run.compare_to ? run.gate !== "fail" : run.pass_at_1 === 1;
  const parts: React.ReactNode[] = [
    <>{pct(run.pass_at_1)} of episodes passed</>,
  ];
  if (run.verdict && run.compare_to) {
    parts.push(
      run.verdict === "regressed" ? <span className="text-bad">significantly worse than its baseline</span>
        : run.verdict === "improved" ? <span className="text-ok">significantly better than its baseline</span>
        : <>no significant change versus its baseline</>,
    );
  } else if (previous) {
    parts.push(<>not compared to a baseline</>);
  }
  return (
    <Link href={`/dashboard/run/?id=${run.id}`} className={`card block p-5 transition-colors hover:border-ember/40 ${passed ? "" : "border-bad/40 bg-bad/[0.04]"}`}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className={`mt-0.5 flex h-8 w-8 items-center justify-center rounded-full ${passed ? "bg-ok/15 text-ok" : "bg-bad/15 text-bad"}`}>
            {passed ? <IconCheck /> : <IconX />}
          </span>
          <div>
            <div className="text-[15px] font-semibold">
              Latest run “{run.label || "unlabeled"}”{" "}
              {run.compare_to ? (passed ? "passed the gate" : "failed the gate") : (passed ? "passed every check" : "has failing scenarios")}
            </div>
            <div className="mt-0.5 text-[13.5px] text-mute">
              {parts.map((p, i) => <span key={i}>{i ? " · " : ""}{p}</span>)} · {run.n_episodes} episodes on {run.model}
            </div>
          </div>
        </div>
        <span className="text-[13px] text-ember">Open run →</span>
      </div>
    </Link>
  );
}

/* ------------------------------------------------------------------ first visit */

function Welcome({ nScenarios }: { nScenarios: number }) {
  const { project, canWrite } = useProject();
  const router = useRouter();
  const doctor = useResource<Doctor>("/api/doctor");
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const smallest = Object.entries(project.suites).sort((a, b) => a[1].scenarios.length - b[1].scenarios.length)[0];

  async function firstRun() {
    setStarting(true);
    setError(null);
    try {
      const r = await api<Run>("/api/runs", {
        method: "POST",
        body: JSON.stringify({ suite: smallest?.[0] ?? null, runs: 1, label: "first run" }),
      });
      router.push(`/dashboard/run/?id=${r.id}`);
    } catch (e) {
      setError((e as Error).message);
      setStarting(false);
    }
  }

  const connected = doctor.data?.ok;
  return (
    <>
      <PageHeader
        title={`Welcome to AgentCrucible`}
        sub={<>Your project <b className="text-fg">{project.project}</b> is loaded with {nScenarios} scenarios. Four steps to your first regression gate.</>}
      />
      <ol className="space-y-4">
        <WelcomeStep n={1} done={connected === true} title="Check the connection" sub="Model server, MCP servers and your agent must all be reachable.">
          {!doctor.data ? (
            <div className="flex items-center gap-2 text-[13px] text-mute"><Spinner /> Checking (starts each MCP server once)…</div>
          ) : (
            <ul className="space-y-1.5">
              {doctor.data.checks.map((c) => (
                <li key={c.id} className="flex items-start gap-2 text-[13px]">
                  <span className={c.ok ? "text-ok" : "text-bad"}>{c.ok ? <IconCheck className="mt-0.5 h-3.5 w-3.5" /> : <IconX className="mt-0.5 h-3.5 w-3.5" />}</span>
                  <span><b className="font-medium">{c.label}</b> <span className="text-mute">· {c.detail}</span></span>
                </li>
              ))}
            </ul>
          )}
          {doctor.data && !doctor.data.ok && (
            <div className="mt-3"><Button variant="secondary" href="/dashboard/setup/">Fix in Setup</Button></div>
          )}
        </WelcomeStep>

        <WelcomeStep n={2} title="Run your first test" sub={`Runs the “${smallest?.[0]}” suite once (${smallest?.[1].scenarios.length} scenarios). Takes a minute or two on a local model.`}>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={firstRun} disabled={starting || connected === false || !canWrite} title={canWrite ? undefined : "Read-only access: sign in with the full-access token to start runs"}>
              {starting ? <><Spinner /> Starting…</> : "Run first test"}
            </Button>
            {canWrite && <Button variant="ghost" href="/dashboard/runs/?new=1">Choose what to run</Button>}
          </div>
          {error && <div className="mt-2 text-[12.5px] text-bad">{error}</div>}
        </WelcomeStep>

        <WelcomeStep n={3} title="Make it your baseline" sub="Run with 5 attempts per scenario on your main branch, then compare every change against it. AgentCrucible only flags differences that are statistically real." />

        <WelcomeStep n={4} title="Gate pull requests" sub="Add the GitHub Action so every PR gets a comparison comment and a pass/fail check.">
          <Button variant="secondary" href={`${GITHUB}/blob/main/docs/ADOPTION.md#5-baseline-and-ci`} external>Read the CI guide</Button>
        </WelcomeStep>
      </ol>
    </>
  );
}

function WelcomeStep({ n, title, sub, done, children }: { n: number; title: string; sub: string; done?: boolean; children?: React.ReactNode }) {
  return (
    <li className="card flex gap-4 p-5">
      <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-mono text-[13px] ${done ? "bg-ok/15 text-ok" : "bg-ember/15 text-ember"}`}>
        {done ? <IconCheck /> : n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-[15px] font-semibold">{title}</div>
        <div className="mt-0.5 text-[13.5px] text-mute">{sub}</div>
        {children && <div className="mt-3">{children}</div>}
      </div>
    </li>
  );
}

function Loading() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), 4000);
    return () => clearTimeout(t);
  }, []);
  return (
    <div className="flex items-center justify-center gap-3 py-40 text-[13px] text-dim">
      <Spinner /> {slow ? "Still loading…" : "Loading…"}
    </div>
  );
}
