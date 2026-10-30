"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useMemo, useState } from "react";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { RunStatus } from "@/components/app/bits";
import { useRuns } from "@/components/app/hooks";
import { IconPlus, IconRuns, IconX } from "@/components/Icons";
import { Button, Card, Empty, PassRate, Spinner } from "@/components/ui";
import { api, type Run } from "@/lib/api";
import { duration, pct, when } from "@/lib/format";

export default function RunsPage() {
  return (
    <Suspense>
      <Runs />
    </Suspense>
  );
}

function Runs() {
  const params = useSearchParams();
  const [open, setOpen] = useState(params.get("new") === "1");
  const runs = useRuns();
  const { canWrite } = useProject();

  return (
    <>
      <PageHeader
        title="Runs"
        sub="Each run plays every selected scenario several times against your agent and grades what it did. Compare a run against a baseline to see whether a change made things better or worse."
        actions={!open && <Button onClick={() => setOpen(true)} disabled={!canWrite} title={canWrite ? undefined : "Read-only access: sign in with the full-access token to start runs"}><IconPlus /> New run</Button>}
      />
      {/* rendered once runs are loaded, so "Compare with" can default to the latest finished run */}
      {open && canWrite && runs.data && <NewRun runs={runs.data} onClose={() => setOpen(false)} />}
      <Card>
        {!runs.data ? (
          <div className="flex items-center justify-center gap-2 py-16 text-[13px] text-dim"><Spinner /> Loading runs…</div>
        ) : runs.data.length === 0 ? (
          <Empty icon={<IconRuns />} title="No runs yet" action={!open && canWrite && <Button onClick={() => setOpen(true)}><IconPlus /> Start your first run</Button>}>
            A run takes a minute or two on a local model. You&apos;ll see each scenario pass or fail, and exactly why.
          </Empty>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-left text-[13px]">
              <thead>
                <tr className="border-b border-line text-[11.5px] text-dim">
                  {["Run", "Result", "Pass rate", "All attempts pass", "Compared with", "Model", "Started"].map((h) => (
                    <th key={h} className="px-5 py-3 font-medium">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {runs.data.map((r) => <Row key={r.id} r={r} all={runs.data!} />)}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function Row({ r, all }: { r: Run; all: Run[] }) {
  const router = useRouter();
  const base = r.compare_to ? all.find((x) => x.id === r.compare_to) : null;
  return (
    <tr onClick={() => router.push(`/dashboard/run/?id=${r.id}`)} className="cursor-pointer border-b border-line/60 last:border-0 hover:bg-white/[0.03]">
      <td className="px-5 py-3.5">
        <Link href={`/dashboard/run/?id=${r.id}`} className="font-medium hover:text-ember" onClick={(e) => e.stopPropagation()}>
          {r.label || <span className="text-mute">unlabeled run</span>}
        </Link>
        <div className="font-mono text-[11px] text-dim">{r.params?.agent ? `agent ${r.params.agent}` : r.suite ?? "all suites"} · {r.n_episodes ?? r.progress?.total ?? "–"} episodes</div>
      </td>
      <td className="px-5 py-3.5"><RunStatus r={r} /></td>
      <td className="px-5 py-3.5"><PassRate value={r.pass_at_1} /></td>
      <td className="px-5 py-3.5 font-mono text-mute">{pct(r.pass_pow_k)}{r.k ? <span className="text-dim"> · k={r.k}</span> : null}</td>
      <td className="px-5 py-3.5 text-mute">
        {base ? (
          <span>
            {base.label || "baseline"}{" "}
            <span className={r.verdict === "regressed" ? "text-bad" : r.verdict === "improved" ? "text-ok" : "text-dim"}>· {r.verdict ?? "…"}</span>
          </span>
        ) : <span className="text-dim">–</span>}
      </td>
      <td className="px-5 py-3.5 font-mono text-[12px] text-mute">{r.model}</td>
      <td className="whitespace-nowrap px-5 py-3.5 text-mute">{when(r.created_at)}</td>
    </tr>
  );
}

/* ------------------------------------------------------------------ new run */

function NewRun({ runs, onClose }: { runs: Run[]; onClose: () => void }) {
  const { project, models } = useProject();
  const router = useRouter();
  const suites = Object.entries(project.suites);
  const allScenarios = suites.flatMap(([suite, s]) => s.scenarios.map((sc) => ({ ...sc, suite })));

  const multi = project.agents.length > 1;
  const [scope, setScope] = useState<"all" | "agent" | "suite" | "pick">("all");
  const [agent, setAgent] = useState(project.agents[0]?.name ?? "");
  const [suite, setSuite] = useState(suites[0]?.[0] ?? "");
  const [picked, setPicked] = useState<string[]>([]);
  const [k, setK] = useState(3);
  const [model, setModel] = useState("");
  const [label, setLabel] = useState("");
  const [prompt, setPrompt] = useState("");
  const [extraEnv, setExtraEnv] = useState("");
  // a baseline only means something for the same set of scenarios: default to the latest run of the same scope
  const baselineFor = (sc: typeof scope, ag: string, su: string) => runs.find((r) => r.status === "done"
    && (r.params?.agent ?? null) === (sc === "agent" ? ag : null) && (r.suite ?? null) === (sc === "suite" ? su : null)
    && !(r.params?.scenarios?.length))?.id ?? "";
  const [compare, setCompare] = useState(() => baselineFor("all", agent, suite));
  const pick = (sc: typeof scope, ag = agent, su = suite) => {
    setScope(sc);
    setAgent(ag);
    setSuite(su);
    setCompare(sc === "pick" ? "" : baselineFor(sc, ag, su));
  };
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const nScenarios = scope === "all" ? allScenarios.length : scope === "agent" ? project.agents.find((a) => a.name === agent)?.scenarios ?? 0
    : scope === "suite" ? project.suites[suite]?.scenarios.length ?? 0 : picked.length;
  // scenarios of an agent whose adapter is still the generated scaffold are skipped by the run
  const scaffoldSuites = new Set(project.agents.filter((a) => a.scaffold).flatMap((a) => a.suites));
  const chosen = scope === "all" ? allScenarios : scope === "agent" ? allScenarios.filter((s) => project.agents.find((a) => a.name === agent)?.suites.includes(s.suite))
    : scope === "suite" ? allScenarios.filter((s) => s.suite === suite) : allScenarios.filter((s) => picked.includes(s.id));
  const nSkipped = chosen.filter((s) => scaffoldSuites.has(s.suite)).length;
  const episodes = (nScenarios - nSkipped) * k;
  const perEpisode = useMemo(() => {
    // only runs whose agents actually ran: episodes that crash at once would make every estimate look instant
    const done = runs.filter((r) => r.status === "done" && r.finished_at && r.n_episodes && (r.summary?.errors ?? 0) < r.n_episodes / 2);
    if (!done.length) return null;
    const secs = done.map((r) => (new Date(r.finished_at!).getTime() - new Date(r.created_at).getTime()) / 1000 / r.n_episodes!);
    return secs.reduce((a, b) => a + b, 0) / secs.length;
  }, [runs]);
  const baselines = runs.filter((r) => r.status === "done");

  async function start(e: React.FormEvent) {
    e.preventDefault();
    if (!nScenarios) return setError("Pick at least one scenario.");
    setBusy(true);
    setError(null);
    const env: Record<string, string> = {};
    if (prompt) env.AGENT_PROMPT = prompt;
    extraEnv.split("\n").map((l) => l.trim()).filter(Boolean).forEach((l) => {
      const i = l.indexOf("=");
      if (i > 0) env[l.slice(0, i).trim()] = l.slice(i + 1).trim();
    });
    try {
      const r = await api<Run>("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          suite: scope === "suite" ? suite : null,
          agent: scope === "agent" ? agent : null,
          scenarios: scope === "pick" ? picked : null,
          runs: k, model: model || null, label, agent_env: env, compare: compare || null,
        }),
      });
      router.push(`/dashboard/run/?id=${r.id}`);
    } catch (err) {
      setError((err as Error).message);
      setBusy(false);
    }
  }

  // no font size here: the env textarea uses a smaller mono size, and two text-[…] classes would conflict
  const field = "w-full rounded-lg border border-line bg-panel-2 px-3 py-2 outline-none focus:border-ember/60";
  const input = `${field} text-[13.5px]`;
  return (
    <form onSubmit={start} className="card mb-6 overflow-hidden">
      <div className="flex items-center justify-between border-b border-line px-5 py-4">
        <div>
          <h2 className="text-[16px] font-semibold">New run</h2>
          <p className="text-[13px] text-mute">Choose what to test and how hard. Defaults are fine for a first look.</p>
        </div>
        <button type="button" onClick={onClose} className="rounded-lg p-1.5 text-mute hover:bg-white/5 hover:text-fg" aria-label="Close"><IconX /></button>
      </div>

      <div className="grid gap-6 p-5 lg:grid-cols-2">
        <div className="space-y-5">
          <Field label="What to test">
            <div className="flex flex-wrap gap-2">
              {([["all", multi ? `All agents (${project.agents.length})` : `Everything (${allScenarios.length})`], ...(multi ? [["agent", "One agent"]] : []), ["suite", "One suite"], ["pick", "Pick scenarios"]] as [typeof scope, string][]).map(([v, l]) => (
                <Chip key={v} on={scope === v} onClick={() => pick(v)}>{l}</Chip>
              ))}
            </div>
            {scope === "agent" && (
              <select value={agent} onChange={(e) => pick("agent", e.target.value)} className={`${input} mt-3`}>
                {project.agents.map((a) => <option key={a.name} value={a.name}>{a.name} · {a.scenarios} scenarios</option>)}
              </select>
            )}
            {scope === "suite" && (
              <select value={suite} onChange={(e) => pick("suite", agent, e.target.value)} className={`${input} mt-3`}>
                {suites.map(([n, s]) => <option key={n} value={n}>{n} · {s.scenarios.length} scenarios</option>)}
              </select>
            )}
            {scope === "pick" && (
              <div className="mt-3 max-h-52 space-y-1 overflow-y-auto rounded-lg border border-line bg-panel-2 p-2">
                {allScenarios.map((s) => (
                  <label key={s.id} className="flex cursor-pointer items-start gap-2.5 rounded-md px-2 py-1.5 hover:bg-white/[0.04]">
                    <input type="checkbox" className="mt-0.5 accent-[#ff6b35]" checked={picked.includes(s.id)}
                      onChange={(e) => setPicked(e.target.checked ? [...picked, s.id] : picked.filter((x) => x !== s.id))} />
                    <span className="min-w-0">
                      <span className="block font-mono text-[12.5px]">{s.id}</span>
                      <span className="block truncate text-[12px] text-dim">{s.description}</span>
                    </span>
                  </label>
                ))}
              </div>
            )}
          </Field>

          <Field label="Attempts per scenario" hint="Agents are non-deterministic, so each scenario runs several times. 3 is enough to explore; use 5 or more for a baseline you gate on.">
            <div className="flex flex-wrap gap-2">
              {[1, 3, 5, 10].map((n) => <Chip key={n} on={k === n} onClick={() => setK(n)}>{n}×</Chip>)}
            </div>
          </Field>

          <Field label="Compare with" hint="Pick a baseline to get a verdict (better / worse / no significant change) for every scenario.">
            <select value={compare} onChange={(e) => setCompare(e.target.value)} className={input}>
              <option value="">Don&apos;t compare</option>
              {baselines.map((r) => <option key={r.id} value={r.id}>{r.label || r.id} · {pct(r.pass_at_1)} · {when(r.created_at)}</option>)}
            </select>
          </Field>
        </div>

        <div className="space-y-5">
          <Field label="Name this run" hint="Shows up in history and PR comments, e.g. the prompt or branch you are testing.">
            <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. new-system-prompt" className={input} />
          </Field>

          <Field label="Model" hint="Forced on every LLM call your agent makes, so the same suite can compare models.">
            <select value={model} onChange={(e) => setModel(e.target.value)} className={input}>
              <option value="">{project.model} (project default)</option>
              {models.filter((m) => m !== project.model).map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </Field>

          {project.prompt_presets.length > 0 && (
            <Field label="Agent prompt" hint="Passed to your agent as AGENT_PROMPT. Try a variant against the baseline.">
              <div className="flex flex-wrap gap-2">
                <Chip on={!prompt} onClick={() => setPrompt("")}>agent default</Chip>
                {project.prompt_presets.map((p) => <Chip key={p} on={prompt === p} onClick={() => setPrompt(p)}>{p.replace(/^prompts\//, "")}</Chip>)}
              </div>
            </Field>
          )}

          <details className="group">
            <summary className="cursor-pointer text-[12.5px] text-mute hover:text-fg">More agent settings</summary>
            <div className="mt-3">
              <Field label="Environment variables for the agent" hint="One KEY=VALUE per line.">
                <textarea value={extraEnv} onChange={(e) => setExtraEnv(e.target.value)} rows={3} className={`${field} font-mono text-[12.5px]`} placeholder="FEATURE_FLAG=on" />
              </Field>
            </div>
          </details>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-panel/60 px-5 py-4">
        <div className="text-[13px] text-mute">
          <b className="text-fg">{episodes} episodes</b> ({nScenarios - nSkipped} scenarios × {k})
          {nSkipped > 0 && <> · {nSkipped} skipped: their agent&apos;s adapter is still a scaffold (Setup)</>}
          {perEpisode && episodes > 0 ? <> · about {duration(perEpisode * episodes)} based on past runs</> : null}
        </div>
        <div className="flex items-center gap-3">
          {error && <span className="text-[12.5px] text-bad">{error}</span>}
          <Button variant="ghost" onClick={onClose}>Cancel</Button>
          <Button type="submit" disabled={busy || !episodes}>{busy ? <><Spinner /> Starting…</> : "Start run"}</Button>
        </div>
      </div>
    </form>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="mb-1.5 text-[13px] font-medium">{label}</div>
      {children}
      {hint && <div className="mt-1.5 text-[12px] leading-relaxed text-dim">{hint}</div>}
    </div>
  );
}

function Chip({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button type="button" onClick={onClick}
      className={`rounded-full border px-3 py-1.5 text-[12.5px] transition-colors ${on ? "border-ember/60 bg-ember/10 text-fg" : "border-line text-mute hover:text-fg"}`}>
      {children}
    </button>
  );
}
