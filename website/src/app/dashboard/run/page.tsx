"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useState } from "react";
import { useProject } from "@/components/app/AppShell";
import { RunStatus } from "@/components/app/bits";
import { useResource } from "@/components/app/hooks";
import { IconArrow, IconCheck, IconExternal, IconRefresh, IconX } from "@/components/Icons";
import { flaggedTools, TrajectoryTimeline } from "@/components/TrajectoryTimeline";
import { Badge, Button, Card, CardHeader, Dots, Empty, PassRate, Spinner, Stat } from "@/components/ui";
import { api, reportUrl, type ComparisonRow, type Episode, type Run, type RunDetail, type TrajectoryEvent } from "@/lib/api";
import { CHECK_HELP, duration, pct, signedPts, when } from "@/lib/format";

export default function RunPage() {
  return (
    <Suspense>
      <RunView />
    </Suspense>
  );
}

function RunView() {
  const params = useSearchParams();
  const id = params.get("id");
  const { data, error } = useResource<RunDetail>(id ? `/api/runs/${id}` : null,
    (d) => d.run.status === "queued" || d.run.status === "running", 2000);

  if (!id) return <Empty title="No run selected" action={<Button href="/dashboard/runs/">Go to runs</Button>} />;
  if (error && !data) return <Empty title="Couldn't load this run">{error}</Empty>;
  if (!data) return <div className="flex items-center justify-center gap-2 py-40 text-[13px] text-dim"><Spinner /> Loading run…</div>;

  const r = data.run;
  return (
    <>
      <Link href="/dashboard/runs/" className="text-[13px] text-mute hover:text-fg">← All runs</Link>
      <div className="mb-6 mt-3 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[26px] font-semibold tracking-tight">{r.label || "Unlabeled run"}</h1>
            <RunStatus r={r} />
          </div>
          <p className="mt-1 font-mono text-[12px] text-dim">
            {when(r.created_at)} · {r.model} · {r.suite ?? "all suites"} · {r.k}× per scenario · {r.id}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <RunAgain run={r} />
          {r.status === "done" && <Button variant="secondary" href={reportUrl(r.id)} external>HTML report <IconExternal className="h-3.5 w-3.5" /></Button>}
        </div>
      </div>

      {(r.status === "queued" || r.status === "running") && <Progress detail={data} />}
      {r.status === "failed" && (
        <Card className="border-bad/40 p-5">
          <div className="text-[15px] font-semibold text-bad">The run stopped with an error</div>
          <pre className="code mt-2 whitespace-pre-wrap text-mute">{r.error}</pre>
          <div className="mt-3 text-[13px] text-mute">
            Usually the model server or an MCP server isn&apos;t reachable. <Link href="/dashboard/setup/" className="text-ember">Run the connection check →</Link>
          </div>
        </Card>
      )}
      {r.status === "done" && data.summary && <Results detail={data} />}
      {r.status === "done" && !data.summary && (
        <Card className="p-5">
          <div className="text-[15px] font-semibold">This run&apos;s result files are no longer available</div>
          <p className="mt-1 text-[13.5px] text-mute">
            The history entry is still in the database, but its trajectories were removed (for example a cleared results
            volume). Pass rate {pct(r.pass_at_1)} over {r.n_episodes} episodes was recorded.
          </p>
        </Card>
      )}
    </>
  );
}

function RunAgain({ run }: { run: Run }) {
  const router = useRouter();
  const { canWrite } = useProject();
  const [busy, setBusy] = useState(false);
  const p = run.params as (Record<string, unknown> & { agent_env?: Record<string, string> }) | undefined;
  // runs imported from CLI history have no API parameters to repeat
  if (!canWrite || !p || p.imported || run.status === "running" || run.status === "queued") return null;
  return (
    <Button variant="secondary" disabled={busy} onClick={async () => {
      setBusy(true);
      try {
        const r = await api<Run>("/api/runs", { method: "POST", body: JSON.stringify({ ...p, label: `${run.label || "run"} (again)` }) });
        router.push(`/dashboard/run/?id=${r.id}`);
      } catch { setBusy(false); }
    }}>
      {busy ? <Spinner /> : <IconRefresh />} Run again
    </Button>
  );
}

function Progress({ detail }: { detail: RunDetail }) {
  const p = detail.progress;
  return (
    <Card className="p-6">
      <div className="flex items-center gap-3">
        <Spinner className="h-5 w-5 text-info" />
        <div>
          <div className="text-[16px] font-semibold">{detail.run.status === "queued" ? "Waiting for the previous run to finish" : "Running your agent through the scenarios"}</div>
          <div className="text-[13px] text-mute">
            {p ? `${p.done} of ${p.total} episodes finished${p.failed ? ` · ${p.failed} failed so far` : ""}` : "Starting the gateways and sandboxes…"}
          </div>
        </div>
      </div>
      <div className="mt-5 h-2 overflow-hidden rounded-full bg-panel-2">
        <div className="h-full rounded-full bg-info transition-all duration-500" style={{ width: `${p ? (100 * p.done) / p.total : 3}%` }} />
      </div>
      <p className="mt-4 text-[12.5px] text-dim">
        Each episode starts fresh MCP servers and a clean environment, plays the conversation, then grades it. This page updates by itself.
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ results */

function Results({ detail }: { detail: RunDetail }) {
  const s = detail.summary!;
  const params = useSearchParams();
  const cmp = detail.comparison;
  const cmpBy = useMemo(() => new Map((cmp?.scenarios ?? []).map((c) => [c.scenario_id, c])), [cmp]);
  const rows = useMemo(() => {
    const list = (detail.scenarios ?? []).slice();
    // failing first, then by pass rate
    return list.sort((a, b) => a.pass_rate - b.pass_rate || a.id.localeCompare(b.id));
  }, [detail.scenarios]);
  const initial = params.get("scenario") ?? rows.find((r) => r.passed < r.n)?.id ?? rows[0]?.id ?? null;
  const [selected, setSelected] = useState<string | null>(initial);

  return (
    <>
      <Verdict detail={detail} />
      <div className="mt-5 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Episodes passed" value={pct(s.pass_at_1)} sub={`95% confidence: ${pct(s.pass_at_1_ci[0])} – ${pct(s.pass_at_1_ci[1])}`}
          tone={s.pass_at_1 >= 0.9 ? "ok" : s.pass_at_1 >= 0.6 ? "warn" : "bad"} />
        <Stat label={s.k === 1 ? "Scenarios passed" : `Scenarios passing all ${s.k} attempts`} value={pct(s.pass_pow_k)} sub={s.k === 1 ? "run more attempts to measure reliability" : "what users experience every time"} />
        <Stat label="Flaky scenarios" value={s.flaky_scenarios.length} sub="pass sometimes, fail sometimes" tone={s.flaky_scenarios.length ? "warn" : undefined} />
        <Stat label="Episode time" value={duration(s.duration_p50_s)} sub={`slowest 5%: ${duration(s.duration_p95_s)} · ${Math.round(s.tokens_per_episode)} tokens`} />
      </div>

      <Card className="mt-5">
        <CardHeader title="Scenarios" sub="Failing scenarios first. Select one to see every attempt step by step." />
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-left text-[13px]">
            <thead>
              <tr className="border-b border-line text-[11.5px] text-dim">
                <th className="px-5 py-2.5 font-medium">Scenario</th>
                <th className="px-5 py-2.5 font-medium">Attempts</th>
                <th className="px-5 py-2.5 font-medium">Pass rate</th>
                {cmp && <th className="px-5 py-2.5 font-medium">vs baseline</th>}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const c = cmpBy.get(row.id);
                const on = selected === row.id;
                return (
                  <tr key={row.id} onClick={() => setSelected(row.id)}
                    className={`cursor-pointer border-b border-line/60 last:border-0 ${on ? "bg-white/[0.05]" : "hover:bg-white/[0.03]"}`}>
                    <td className="px-5 py-3">
                      <div className="flex items-center gap-2">
                        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${on ? "bg-ember" : "bg-transparent"}`} />
                        <span className="font-mono text-[12.5px]">{row.id}</span>
                        {row.flaky && <Badge tone="warn">flaky</Badge>}
                      </div>
                      <div className="ml-3.5 truncate text-[12px] text-dim">{detail.scenario_meta?.[row.id]?.description}</div>
                    </td>
                    <td className="px-5 py-3"><Dots passed={row.passed} n={row.n} /></td>
                    <td className="px-5 py-3"><PassRate value={row.pass_rate} /> <span className="font-mono text-[11.5px] text-dim">{row.passed}/{row.n}</span></td>
                    {cmp && <td className="px-5 py-3">{c ? <CmpCell c={c} /> : <span className="text-dim">not in baseline</span>}</td>}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Card>

      {selected && <ScenarioDetail key={selected} runId={detail.run.id} scenarioId={selected}
        episodes={(detail.episodes ?? []).filter((e) => e.scenario_id === selected).sort((a, b) => a.attempt - b.attempt)} />}
    </>
  );
}

function CmpCell({ c }: { c: ComparisonRow }) {
  const tone = c.verdict === "regressed" ? "bad" : c.verdict === "improved" ? "ok" : c.verdict === "inconclusive" ? "warn" : "mute";
  const title = c.verdict === "inconclusive"
    ? `Changed from ${c.base_passed}/${c.base_n} to ${c.cand_passed}/${c.cand_n}, but that could still be chance${c.runs_needed ? `; about ${c.runs_needed} attempts per side would settle it` : ""}.`
    : `${c.base_passed}/${c.base_n} → ${c.cand_passed}/${c.cand_n} (adjusted p = ${c.p_adj.toFixed(3)})`;
  return (
    <span title={title} className="inline-flex items-center gap-2">
      <Badge tone={tone}>{c.verdict === "inconclusive" ? (c.delta < 0 ? "looks worse" : "looks better") : c.verdict}</Badge>
      <span className="font-mono text-[11.5px] text-dim">{c.base_passed}/{c.base_n} → {c.cand_passed}/{c.cand_n}</span>
      {c.verdict === "inconclusive" && c.runs_needed ? <span className="text-[11.5px] text-dim">· needs ≈{c.runs_needed}×</span> : null}
    </span>
  );
}

function Verdict({ detail }: { detail: RunDetail }) {
  const r = detail.run;
  const cmp = detail.comparison;
  const failed = r.gate === "fail";
  let headline = "";
  let body: React.ReactNode = null;
  if (cmp) {
    const [lo, hi] = cmp.overall.ci;
    headline = cmp.overall.verdict === "regressed" ? "Worse than the baseline" : cmp.overall.verdict === "improved" ? "Better than the baseline" : "No significant change from the baseline";
    body = (
      <>
        Pass rate moved {signedPts(cmp.overall.delta)}. With 95% confidence the real change is between {signedPts(lo)} and {signedPts(hi)}
        {cmp.overall.verdict === "unchanged" ? ", which includes zero, so this could be noise." : "."}
        {cmp.counts.inconclusive ? ` ${cmp.counts.inconclusive} scenario${cmp.counts.inconclusive > 1 ? "s" : ""} changed but need more attempts to be sure.` : ""}
      </>
    );
  } else {
    const total = detail.scenarios?.length ?? 0;
    const failing = (detail.scenarios ?? []).filter((x) => x.passed < x.n).length;
    const warn = failing > 0;
    return (
      <div className={`card flex items-start gap-4 p-5 ${warn ? "border-warn/40 bg-warn/[0.04]" : ""}`}>
        <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${warn ? "bg-warn/15 text-warn" : "bg-ok/15 text-ok"}`}>
          {warn ? <IconX /> : <IconCheck />}
        </span>
        <div className="min-w-0">
          <div className="text-[16px] font-semibold">
            {warn ? `${failing} of ${total} scenario${total === 1 ? "" : "s"} failed at least once` : `All ${total} scenarios passed every attempt`}
          </div>
          <div className="mt-1 text-[13.5px] leading-relaxed text-mute">
            This run wasn&apos;t compared with a baseline, so there is no better/worse verdict yet. The CI gate fails on
            regressions, so it needs a baseline to compare against: start a new run with “Compare with” set to this one.
          </div>
        </div>
      </div>
    );
  }
  return (
    <div className={`card flex items-start gap-4 p-5 ${failed ? "border-bad/40 bg-bad/[0.04]" : ""}`}>
      <span className={`mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-full ${failed ? "bg-bad/15 text-bad" : "bg-ok/15 text-ok"}`}>
        {failed ? <IconX /> : <IconCheck />}
      </span>
      <div className="min-w-0">
        <div className="text-[16px] font-semibold">{headline} · <span className={failed ? "text-bad" : "text-ok"}>CI gate {failed ? "would fail" : "would pass"}</span></div>
        <div className="mt-1 text-[13.5px] leading-relaxed text-mute">{body}</div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ one scenario */

function ScenarioDetail({ runId, scenarioId, episodes }: { runId: string; scenarioId: string; episodes: Episode[] }) {
  const firstBad = episodes.find((e) => !e.passed) ?? episodes[0];
  const [epId, setEpId] = useState(firstBad?.episode_id);
  const ep = episodes.find((e) => e.episode_id === epId);
  const [events, setEvents] = useState<TrajectoryEvent[] | null>(null);

  useEffect(() => {
    if (!epId) return;
    let live = true;
    api<{ events: TrajectoryEvent[] }>(`/api/runs/${runId}/episodes/${encodeURIComponent(epId)}`)
      .then((d) => live && setEvents(d.events)).catch(() => live && setEvents([]));
    return () => { live = false; };
  }, [runId, epId]);

  if (!ep) return null;
  return (
    <Card className="mt-5">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-line px-5 py-4">
        <div>
          <div className="font-mono text-[14px] font-semibold">{scenarioId}</div>
          <div className="text-[12.5px] text-mute">Attempt {ep.attempt} · {ep.totals.llm_calls} LLM calls · {ep.totals.tool_calls} tool calls · {ep.totals.turns} turns · {duration(ep.totals.duration_s)}</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {episodes.map((e) => (
            <button key={e.episode_id} onClick={() => { setEvents(null); setEpId(e.episode_id); }}
              className={`flex items-center gap-1.5 rounded-full border px-3 py-1 text-[12.5px] ${e.episode_id === epId ? "border-ember/60 bg-ember/10" : "border-line text-mute hover:text-fg"}`}>
              <span className={e.passed ? "text-ok" : "text-bad"}>{e.passed ? "✓" : "✗"}</span> attempt {e.attempt}
            </button>
          ))}
        </div>
      </div>
      <div className="grid lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.4fr)]">
        <div className="border-b border-line p-5 lg:border-b-0 lg:border-r">
          <div className="mb-3 text-[11.5px] font-medium uppercase tracking-[0.12em] text-dim">Checks</div>
          {ep.error && <div className="mb-3 rounded-lg border border-bad/30 bg-bad/[0.06] px-3 py-2 text-[12.5px] text-bad">{ep.error}</div>}
          <ul className="space-y-3">
            {ep.checks.map((c, i) => (
              <li key={i} className="text-[13px]">
                <div className="flex items-start gap-2">
                  <span className={`mt-0.5 ${c.passed ? "text-ok" : c.hard ? "text-bad" : "text-warn"}`}>{c.passed ? <IconCheck className="h-3.5 w-3.5" /> : <IconX className="h-3.5 w-3.5" />}</span>
                  <div className="min-w-0">
                    <div>
                      <span className="font-medium">{CHECK_HELP[c.label] ?? c.label}</span>
                      {!c.hard && <Badge className="ml-1.5">informational</Badge>}
                    </div>
                    <code className="font-mono text-[11px] text-dim">{c.label}</code>
                    <div className="mt-0.5 break-words text-[12.5px] leading-snug text-mute">{c.detail}</div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
        <div className="max-h-[640px] min-w-0 overflow-y-auto">
          <div className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-panel px-5 py-2.5 text-[11.5px] font-medium uppercase tracking-[0.12em] text-dim">
            Trajectory <span className="normal-case tracking-normal">every message, model call and tool call</span>
          </div>
          {events ? <TrajectoryTimeline events={events} flagged={flaggedTools(ep.checks)} /> : <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-dim"><Spinner /> Loading trajectory…</div>}
        </div>
      </div>
      <div className="border-t border-line px-5 py-3 text-right">
        <Link href="/dashboard/scenarios/" className="text-[12.5px] text-mute hover:text-fg">About this scenario <IconArrow className="inline h-3.5 w-3.5" /></Link>
      </div>
    </Card>
  );
}
