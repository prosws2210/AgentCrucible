"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

// Same origin behind nginx (/api → backend). For `npm run dev`, set NEXT_PUBLIC_API_BASE=http://localhost:8000
const API = process.env.NEXT_PUBLIC_API_BASE ?? "";

type Run = {
  id: string;
  label: string;
  suite: string | null;
  model: string;
  status: "queued" | "running" | "done" | "failed";
  created_at: string;
  k: number | null;
  n_episodes: number | null;
  pass_at_1: number | null;
  pass_pow_k: number | null;
  compare_to: string | null;
  verdict: string | null;
  gate: string | null;
  error: string | null;
  progress?: { done: number; total: number; failed: number };
};

type Project = {
  project: string;
  model: string;
  suites: Record<string, { runs: number; scenarios: { id: string; description: string; tags: string[] }[] }>;
  mcp_servers: string[];
  prompt_presets: string[];
  fixtures: string[];
};

type Finding = { suite: string; severity: string; title: string; detail: string; tool: string | null };
type Audit = { id: number; server: string; grade: string; overall: number; created_at: string; report?: { findings: Finding[]; scores: Record<string, number> } };

type RunDetail = {
  run: Run;
  scenarios?: { id: string; n: number; passed: number; pass_rate: number; flaky: boolean }[];
  failures?: { scenario_id: string; attempt: number; error: string | null; failed_checks: string[] }[];
  comparison?: {
    overall: { verdict: string; delta: number; ci: [number, number] };
    scenarios: { scenario_id: string; base_passed: number; base_n: number; cand_passed: number; cand_n: number; verdict: string; runs_needed?: number }[];
  };
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, { ...init, headers: { "Content-Type": "application/json", ...init?.headers } });
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {}
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return r.json();
}

const pct = (x: number | null | undefined) => (x == null ? "–" : `${Math.round(x * 100)}%`);
const when = (s: string) =>
  new Date(s).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });

const STATUS: Record<string, string> = {
  queued: "bg-white/5 text-mute",
  running: "bg-info/15 text-info",
  done: "bg-ok/12 text-ok",
  failed: "bg-bad/12 text-bad",
};
const VERDICT: Record<string, string> = { regressed: "text-bad", improved: "text-ok", unchanged: "text-mute", inconclusive: "text-warn" };
const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
const GRADE: Record<string, string> = { A: "text-ok", B: "text-ok", C: "text-warn", D: "text-bad", F: "text-bad" };

export function Dashboard() {
  const [online, setOnline] = useState<boolean | null>(null);
  const [health, setHealth] = useState<{ db: string; llm_url: string; busy: boolean } | null>(null);
  const [project, setProject] = useState<Project | null>(null);
  const [models, setModels] = useState<string[]>([]);
  const [runs, setRuns] = useState<Run[]>([]);
  const [audits, setAudits] = useState<Audit[]>([]);

  const refresh = useCallback(async () => {
    try {
      const [h, rs, as] = await Promise.all([
        api<{ db: string; llm_url: string; busy: boolean }>("/api/health"),
        api<Run[]>("/api/runs"),
        api<Audit[]>("/api/audits"),
      ]);
      setHealth(h);
      setRuns(rs);
      setAudits(as);
      setOnline(true);
    } catch {
      setOnline(false);
    }
  }, []);

  useEffect(() => {
    // Initial load runs once; state updates land after the awaited requests resolve.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    refresh();
    api<Project>("/api/project").then(setProject).catch(() => {});
    api<{ models: string[] }>("/api/models").then((m) => setModels(m.models)).catch(() => {});
  }, [refresh]);

  const active = runs.some((r) => r.status === "queued" || r.status === "running");
  useEffect(() => {
    if (!active) return;
    const t = setInterval(refresh, 2500);
    return () => clearInterval(t);
  }, [active, refresh]);

  if (online === false) return <Offline />;
  if (online === null || !project) return <div className="py-32 text-center font-mono text-[13px] text-dim">connecting to the API…</div>;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="font-mono text-[11.5px] uppercase tracking-[0.18em] text-ember">Dashboard</div>
          <h1 className="mt-2 text-3xl font-semibold tracking-tight">{project.project}</h1>
        </div>
        <div className="flex flex-wrap gap-2 font-mono text-[11.5px]">
          <Pill ok>API online</Pill>
          <Pill ok>db · {health?.db}</Pill>
          <Pill ok={models.length > 0}>{models.length ? `${models.length} models` : "model server unreachable"}</Pill>
          {health?.busy && <Pill>run in progress</Pill>}
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[300px_1fr]">
        <NewRun project={project} models={models} runs={runs} onStarted={refresh} />
        <RunsTable runs={runs} />
      </div>

      <Audits project={project} audits={audits} onDone={refresh} />
    </div>
  );
}

function Pill({ ok = false, children }: { ok?: boolean; children: React.ReactNode }) {
  return (
    <span className={`flex items-center gap-1.5 rounded-full border border-line px-2.5 py-1 ${ok ? "text-mute" : "text-warn"}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-ok" : "bg-warn"}`} />
      {children}
    </span>
  );
}

function Offline() {
  return (
    <div className="card mx-auto mt-10 max-w-2xl p-8">
      <h1 className="text-2xl font-semibold tracking-tight">The API isn&apos;t reachable</h1>
      <p className="mt-3 text-[15px] leading-relaxed text-mute">
        The dashboard talks to the AgentCrucible backend. Start the full stack (frontend, backend, Postgres and an
        Ollama model server) with Docker:
      </p>
      <pre className="code mt-5 overflow-x-auto rounded-xl border border-line bg-panel-2 p-4">{`docker compose up --build
# then open http://localhost:8080/dashboard/`}</pre>
      <p className="mt-4 text-[13.5px] text-dim">
        Or run the backend alone with <code className="font-mono">crucible serve</code> and start this site with{" "}
        <code className="font-mono">NEXT_PUBLIC_API_BASE=http://localhost:8000 npm run dev</code>.
      </p>
    </div>
  );
}

/* ------------------------------------------------------------------ new run */

function NewRun({ project, models, runs, onStarted }: { project: Project; models: string[]; runs: Run[]; onStarted: () => void }) {
  const [suite, setSuite] = useState("");
  const [k, setK] = useState(3);
  const [model, setModel] = useState("");
  const [label, setLabel] = useState("");
  const [env, setEnv] = useState("");
  const [compare, setCompare] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const baselines = runs.filter((r) => r.status === "done");
  const episodes = useMemo(() => {
    const names = suite ? [suite] : Object.keys(project.suites);
    return names.reduce((n, s) => n + project.suites[s].scenarios.length, 0) * k;
  }, [suite, k, project]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const agent_env = Object.fromEntries(
      env.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => {
        const i = l.indexOf("=");
        return [l.slice(0, i), l.slice(i + 1)];
      }),
    );
    try {
      await api("/api/runs", {
        method: "POST",
        body: JSON.stringify({ suite: suite || null, runs: k, model: model || null, label, agent_env, compare: compare || null }),
      });
      onStarted();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const field = "w-full rounded-lg border border-line bg-panel-2 px-3 py-2 text-[13.5px] outline-none focus:border-ember/60";
  return (
    <form onSubmit={submit} className="card h-fit space-y-4 p-5">
      <h2 className="text-[16px] font-semibold">New run</h2>
      <Field label="Suite">
        <select value={suite} onChange={(e) => setSuite(e.target.value)} className={field}>
          <option value="">All suites</option>
          {Object.entries(project.suites).map(([n, s]) => (
            <option key={n} value={n}>{n} · {s.scenarios.length} scenarios</option>
          ))}
        </select>
      </Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Runs per scenario">
          <input type="number" min={1} max={20} value={k} onChange={(e) => setK(Number(e.target.value))} className={field} />
        </Field>
        <Field label="Model">
          <select value={model} onChange={(e) => setModel(e.target.value)} className={field}>
            <option value="">{project.model} (default)</option>
            {models.filter((m) => m !== project.model).map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </Field>
      </div>
      <Field label="Label">
        <input value={label} onChange={(e) => setLabel(e.target.value)} placeholder="e.g. prompt-v2" className={field} />
      </Field>
      <Field label="Agent environment (KEY=VALUE per line)">
        <textarea value={env} onChange={(e) => setEnv(e.target.value)} rows={2} className={`${field} font-mono text-[12.5px]`} />
        {project.prompt_presets.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {project.prompt_presets.map((p) => (
              <button key={p} type="button" onClick={() => setEnv(`AGENT_PROMPT=${p}`)}
                className="rounded-md border border-line px-2 py-0.5 font-mono text-[11px] text-mute hover:text-fg">
                {p}
              </button>
            ))}
          </div>
        )}
      </Field>
      <Field label="Compare against">
        <select value={compare} onChange={(e) => setCompare(e.target.value)} className={field}>
          <option value="">No baseline</option>
          {baselines.map((r) => (
            <option key={r.id} value={r.id}>{r.label || r.id} · {pct(r.pass_at_1)}</option>
          ))}
        </select>
      </Field>
      {error && <div className="rounded-lg border border-bad/30 bg-bad/[0.06] px-3 py-2 text-[12.5px] text-bad">{error}</div>}
      <button disabled={busy} className="w-full rounded-full bg-fg py-2.5 text-[14px] font-semibold text-ink transition-opacity disabled:opacity-50">
        {busy ? "Starting…" : `Start run · ${episodes} episodes`}
      </button>
    </form>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[12px] text-mute">{label}</span>
      {children}
    </label>
  );
}

/* ------------------------------------------------------------------ runs */

function RunsTable({ runs }: { runs: Run[] }) {
  const [open, setOpen] = useState<string | null>(null);
  if (!runs.length)
    return <div className="card flex items-center justify-center p-10 text-[14px] text-mute">No runs yet. Start one on the left.</div>;
  return (
    <div className="card overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[760px] whitespace-nowrap text-left text-[13px]">
          <thead>
            <tr className="border-b border-line font-mono text-[11px] uppercase tracking-[0.1em] text-dim">
              {["Run", "Status", "Model", "pass@1", "pass^k", "vs baseline", "Gate", ""].map((h) => (
                <th key={h} className="px-4 py-3 font-normal">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <RunRow key={r.id} r={r} open={open === r.id} toggle={() => setOpen(open === r.id ? null : r.id)} />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function RunRow({ r, open, toggle }: { r: Run; open: boolean; toggle: () => void }) {
  return (
    <>
      <tr className="cursor-pointer border-b border-line/60 hover:bg-panel" onClick={toggle}>
        <td className="px-4 py-3">
          <div className="font-medium">{r.label || <span className="text-mute">unlabeled</span>}</div>
          <div className="font-mono text-[11px] text-dim">{when(r.created_at)}</div>
        </td>
        <td className="px-4 py-3">
          <span className={`rounded-full px-2 py-0.5 font-mono text-[11px] ${STATUS[r.status]}`}>{r.status}</span>
          {r.progress && (
            <div className="mt-1.5 w-28">
              <div className="h-1 overflow-hidden rounded-full bg-panel-2">
                <div className="h-full bg-info transition-all" style={{ width: `${(100 * r.progress.done) / r.progress.total}%` }} />
              </div>
              <div className="mt-1 font-mono text-[10.5px] text-dim">{r.progress.done}/{r.progress.total} · {r.progress.failed} failed</div>
            </div>
          )}
        </td>
        <td className="px-4 py-3 font-mono text-[12px] text-mute">{r.model}</td>
        <td className="px-4 py-3 font-mono">{pct(r.pass_at_1)}</td>
        <td className="px-4 py-3 font-mono">{pct(r.pass_pow_k)} <span className="text-dim">k={r.k ?? "–"}</span></td>
        <td className={`px-4 py-3 ${VERDICT[r.verdict ?? ""] ?? "text-dim"}`}>{r.verdict ?? "–"}</td>
        <td className="px-4 py-3">
          {r.gate ? <span className={r.gate === "pass" ? "text-ok" : "text-bad"}>{r.gate === "pass" ? "✓ pass" : "✗ fail"}</span> : <span className="text-dim">–</span>}
        </td>
        <td className="px-4 py-3 text-right">
          {r.status === "done" && (
            <a href={`${API}/api/runs/${r.id}/report`} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()}
              className="rounded-md border border-line px-2 py-1 text-[12px] text-mute hover:border-ember/60 hover:text-fg">
              Report ↗
            </a>
          )}
        </td>
      </tr>
      {open && (
        <tr className="border-b border-line/60 bg-panel/50">
          <td colSpan={8} className="whitespace-normal px-4 py-4">
            <RunDetailView id={r.id} error={r.error} />
          </td>
        </tr>
      )}
    </>
  );
}

function RunDetailView({ id, error }: { id: string; error: string | null }) {
  const [d, setD] = useState<RunDetail | null>(null);
  useEffect(() => {
    api<RunDetail>(`/api/runs/${id}`).then(setD).catch(() => {});
  }, [id]);
  if (error) return <div className="font-mono text-[12px] text-bad">{error}</div>;
  if (!d) return <div className="font-mono text-[12px] text-dim">loading…</div>;
  if (!d.scenarios) return <div className="text-[13px] text-mute">Results appear when the run finishes.</div>;
  const cmp = new Map(d.comparison?.scenarios.map((s) => [s.scenario_id, s]));
  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <div>
        <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-dim">Scenarios</div>
        <ul className="space-y-1.5">
          {d.scenarios.map((s) => {
            const c = cmp.get(s.id);
            return (
              <li key={s.id} className="flex items-center justify-between gap-3 text-[12.5px]">
                <span className="truncate font-mono">{s.id}{s.flaky && <span className="ml-1.5 text-warn">flaky</span>}</span>
                <span className="flex shrink-0 items-center gap-3">
                  {c && <span className={`${VERDICT[c.verdict]} text-[11.5px]`}>{c.base_passed}/{c.base_n} → {c.verdict}{c.runs_needed ? ` · k≈${c.runs_needed}` : ""}</span>}
                  <span className={s.passed === s.n ? "text-ok" : s.passed === 0 ? "text-bad" : "text-warn"}>{s.passed}/{s.n}</span>
                </span>
              </li>
            );
          })}
        </ul>
        {d.comparison && (
          <div className={`mt-4 text-[13px] ${VERDICT[d.comparison.overall.verdict]}`}>
            Overall Δ {(d.comparison.overall.delta * 100).toFixed(1)} pts (95% CI {(d.comparison.overall.ci[0] * 100).toFixed(1)} … {(d.comparison.overall.ci[1] * 100).toFixed(1)}) → {d.comparison.overall.verdict}
          </div>
        )}
      </div>
      <div>
        <div className="mb-2 font-mono text-[11px] uppercase tracking-[0.12em] text-dim">Failures ({d.failures?.length ?? 0})</div>
        <ul className="max-h-64 space-y-2 overflow-y-auto">
          {d.failures?.map((f, i) => (
            <li key={i} className="text-[12px]">
              <span className="font-mono text-fg">{f.scenario_id} #{f.attempt}</span>
              <div className="text-mute">{f.error ?? f.failed_checks.join(" · ")}</div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ audits */

function Audits({ project, audits, onDone }: { project: Project; audits: Audit[]; onDone: () => void }) {
  const [busy, setBusy] = useState<string | null>(null);
  const [shown, setShown] = useState<Audit | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(server: string) {
    setBusy(server);
    setError(null);
    try {
      const a = await api<Audit>("/api/audits", {
        method: "POST",
        body: JSON.stringify({ server, fixture: project.fixtures[0] ?? null }),
      });
      setShown(a);
      onDone();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(null);
    }
  }

  async function show(id: number) {
    setShown(await api<Audit>(`/api/audits/${id}`));
  }

  return (
    <section className="card p-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-[16px] font-semibold">MCP server audits</h2>
          <p className="text-[13px] text-mute">Conformance, tool quality, fuzzing, security and latency for this project&apos;s servers.</p>
        </div>
        <div className="flex gap-2">
          {project.mcp_servers.map((s) => (
            <button key={s} onClick={() => run(s)} disabled={busy !== null}
              className="rounded-full border border-line bg-panel-2 px-3.5 py-1.5 text-[13px] hover:border-ember/60 disabled:opacity-50">
              {busy === s ? `Auditing ${s}…` : `Audit ${s}`}
            </button>
          ))}
        </div>
      </div>
      {error && <div className="mt-3 text-[12.5px] text-bad">{error}</div>}
      <div className="mt-5 grid gap-5 lg:grid-cols-[260px_1fr]">
        <ul className="space-y-1.5">
          {audits.length === 0 && <li className="text-[13px] text-dim">No audits yet.</li>}
          {audits.map((a) => (
            <li key={a.id}>
              <button onClick={() => show(a.id)}
                className={`flex w-full items-center justify-between rounded-lg border px-3 py-2 text-left text-[13px] ${shown?.id === a.id ? "border-ember/50 bg-panel" : "border-line hover:bg-panel"}`}>
                <span>
                  <span className="font-medium">{a.server}</span>
                  <span className="ml-2 font-mono text-[11px] text-dim">{when(a.created_at)}</span>
                </span>
                <span className={`font-serif text-[22px] leading-none ${GRADE[a.grade]}`}>{a.grade}</span>
              </button>
            </li>
          ))}
        </ul>
        <div>
          {shown?.report ? (
            <>
              <div className="mb-3 flex flex-wrap gap-2">
                {Object.entries(shown.report.scores).map(([s, v]) => (
                  <span key={s} className="rounded-md border border-line px-2 py-1 font-mono text-[11.5px] text-mute">
                    {s.replace("_", " ")} <span className={v >= 90 ? "text-ok" : v >= 70 ? "text-warn" : "text-bad"}>{v}</span>
                  </span>
                ))}
              </div>
              <ul className="space-y-2">
                {[...shown.report.findings].sort((a, b) => SEV_ORDER[a.severity] - SEV_ORDER[b.severity]).map((f, i) => (
                  <li key={i} className="text-[13px]">
                    <span className={`mr-2 font-mono text-[11px] ${f.severity === "critical" || f.severity === "high" ? "text-bad" : f.severity === "medium" ? "text-warn" : "text-dim"}`}>
                      {f.severity}
                    </span>
                    {f.tool && <code className="mr-1 font-mono text-[12px]">{f.tool}</code>}
                    <span className="text-mute">{f.title}</span>
                  </li>
                ))}
              </ul>
            </>
          ) : (
            <div className="text-[13px] text-dim">Select or run an audit to see findings.</div>
          )}
        </div>
      </div>
    </section>
  );
}
