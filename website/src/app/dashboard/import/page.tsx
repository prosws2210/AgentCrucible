"use client";

import { Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { useGraphLinks } from "@/components/app/graph";
import { IconArrow, IconCheck, IconGit, IconImport, IconRefresh, IconServer, IconShield, IconX } from "@/components/Icons";
import { Badge, Button, Card, CardHeader, Code, Empty, Spinner } from "@/components/ui";
import { API, api, type DAgent, type Discovery, type DTool, type Effect, type ImportJob, type ImportPreview } from "@/lib/api";

const EFFECTS: Effect[] = ["read-only", "writes data", "destructive", "external call", "reads untrusted text"];
const EFFECT_TONE: Record<Effect, "ok" | "warn" | "bad" | "info" | "ember"> = {
  "read-only": "ok", "writes data": "warn", destructive: "bad", "external call": "info", "reads untrusted text": "ember",
};
const STEPS = ["Connect", "Scan", "Review", "Approve", "Results"];
type Tab = "map" | "agents" | "tools" | "questions" | "connection" | "tests" | "graph";

export default function ImportPage() {
  return (
    <Suspense>
      <Import />
    </Suspense>
  );
}

function Import() {
  const params = useSearchParams();
  const router = useRouter();
  const jobId = params.get("job");
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!jobId) return;
    try {
      setJob(await api<ImportJob>(`/api/discover/${jobId}`));
    } catch (e) {
      setError((e as Error).message);
    }
  }, [jobId]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial fetch; state updates after the request
    load();
  }, [load]);
  const busy = job?.status === "scanning" || job?.status === "applying";
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 1000);
    return () => clearInterval(t);
  }, [busy, load]);

  const step = !jobId ? 0 : !job || job.status === "scanning" ? 1 : job.status === "review" || job.status === "failed" ? 2
    : job.status === "applying" ? 3 : 4;

  return (
    <>
      <PageHeader
        title="Import a codebase"
        sub="Point AgentCrucible at a repository. It reads the code (without running it), finds every agent, tool and MCP server, and drafts their tests. Nothing is written until you approve; then the repository becomes a project in this dashboard with all its agents."
        actions={jobId ? <Button variant="secondary" onClick={() => router.push("/dashboard/import/")}><IconImport className="h-3.5 w-3.5" /> New import</Button> : undefined}
      />
      <Stepper step={step} />
      {error && <Card className="mb-5 border-bad/40 p-4 text-[13px] text-bad">{error}</Card>}
      {!jobId && <Connect onStarted={(id) => router.push(`/dashboard/import/?job=${id}`)} />}
      {jobId && !job && !error && <div className="flex items-center gap-2 py-16 text-[13px] text-dim"><Spinner /> Loading…</div>}
      {job && (job.status === "scanning" || job.status === "failed") && <Progress job={job} title={job.status === "failed" ? "The scan failed" : "Reading the code"} />}
      {job?.discovery && (job.status === "review" || job.status === "apply_failed") && <Review job={job} onChange={setJob} />}
      {job && job.status === "applying" && <Progress job={job} title="Writing the tests and smoke-running them" />}
      {job && job.status === "applied" && job.result && <Results job={job} onChange={setJob} />}
      {job && job.status === "apply_failed" && <Card className="mt-5 border-bad/40 p-4 text-[13px] text-bad">Apply failed: {job.error}</Card>}
    </>
  );
}

function Stepper({ step }: { step: number }) {
  return (
    <ol className="mb-6 flex flex-wrap items-center gap-x-2 gap-y-2 text-[12.5px]">
      {STEPS.map((s, i) => (
        <li key={s} className="flex items-center gap-2">
          <span className={`flex h-6 w-6 items-center justify-center rounded-full font-mono text-[11px] ${i < step ? "bg-ok/15 text-ok" : i === step ? "bg-ember/15 text-ember" : "bg-white/5 text-dim"}`}>
            {i < step ? <IconCheck className="h-3 w-3" /> : i + 1}
          </span>
          <span className={i === step ? "font-medium text-fg" : "text-mute"}>{s}</span>
          {i < STEPS.length - 1 && <span className="mx-1 h-px w-6 bg-line" />}
        </li>
      ))}
    </ol>
  );
}

// ---------------------------------------------------------------- 1. connect

function Connect({ onStarted }: { onStarted: (id: string) => void }) {
  const { canWrite } = useProject();
  const [mode, setMode] = useState<"path" | "git">("path");
  const [path, setPath] = useState("");
  const [git, setGit] = useState("");
  const [include, setInclude] = useState("");
  const [useLlm, setUseLlm] = useState(true);
  const [llmUrl, setLlmUrl] = useState("");
  const [llmModel, setLlmModel] = useState("");
  const [roots, setRoots] = useState<{ roots: string[]; suggestions: string[] } | null>(null);
  const [previewed, setPreviewed] = useState<{ key: string; data: ImportPreview | null } | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api<{ roots: string[]; suggestions: string[] }>("/api/discover/roots").then(setRoots).catch(() => setRoots({ roots: [], suggestions: [] }));
  }, []);

  const includes = useMemo(() => include.split(",").map((s) => s.trim()).filter(Boolean), [include]);
  const llm = { use_llm: useLlm, ...(llmUrl.trim() ? { llm_url: llmUrl.trim() } : {}), ...(llmModel.trim() ? { llm_model: llmModel.trim() } : {}) };
  const llmKey = JSON.stringify(llm);
  const previewKey = JSON.stringify([path.trim(), includes, llmKey]);
  // a preview is shown only while it still answers the current inputs
  const preview = previewed?.key === previewKey ? previewed.data : null;
  // what a scan would read and skip, and which model would see the snippets: before anything is read
  useEffect(() => {
    if (mode !== "path" || !path.trim()) return;
    let live = true;
    const t = setTimeout(async () => {
      setPreviewing(true);
      try {
        const p = await api<ImportPreview>("/api/discover/preview", {
          method: "POST", body: JSON.stringify({ path: path.trim(), include: includes, ...JSON.parse(llmKey) }),
        });
        if (live) setPreviewed({ key: previewKey, data: p });
      } catch {
        if (live) setPreviewed({ key: previewKey, data: null });
      } finally {
        if (live) setPreviewing(false);
      }
    }, 450);
    return () => {
      live = false;
      clearTimeout(t);
    };
  }, [mode, path, includes, llmKey, previewKey]);

  async function start() {
    setBusy(true);
    setError(null);
    try {
      const body = mode === "path" ? { path: path.trim() } : { git_url: git.trim() };
      const j = await api<ImportJob>("/api/discover", {
        method: "POST",
        body: JSON.stringify({ ...body, ...llm, include: includes }),
      });
      onStarted(j.id);
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const value = mode === "path" ? path : git;
  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="p-5 sm:p-6">
        <div className="mb-4 inline-flex rounded-full border border-line bg-panel-2 p-0.5 text-[13px]">
          {(["path", "git"] as const).map((m) => (
            <button key={m} onClick={() => setMode(m)}
              className={`rounded-full px-3.5 py-1.5 ${mode === m ? "bg-white/[0.08] text-fg" : "text-mute hover:text-fg"}`}>
              {m === "path" ? "A folder on this machine" : "A Git URL"}
            </button>
          ))}
        </div>
        <label htmlFor="import-source" className="block text-[13px] font-medium">{mode === "path" ? "Repository folder" : "Git URL"}</label>
        <input id="import-source" value={value} onChange={(e) => (mode === "path" ? setPath : setGit)(e.target.value)}
          placeholder={mode === "path" ? (roots?.suggestions[0] ?? "/path/to/your/repo") : "https://github.com/your-org/agent-service.git"}
          className="mt-1.5 w-full rounded-lg border border-line bg-panel-2 px-3.5 py-2.5 font-mono text-[13px] outline-none focus:border-ember/70" />
        {mode === "path" && roots && roots.suggestions.length > 0 && (
          <div className="mt-3">
            <div className="mb-1.5 text-[12px] text-dim">Projects found</div>
            <div className="flex flex-wrap gap-1.5">
              {roots.suggestions.slice(0, 10).map((s) => (
                <button key={s} onClick={() => setPath(s)}
                  className={`max-w-full truncate rounded-full border px-2.5 py-1 font-mono text-[11.5px] ${path === s ? "border-ember/60 bg-ember/10 text-fg" : "border-line text-mute hover:text-fg"}`}>
                  {s.split(/[\\/]/).slice(-2).join("/")}
                </button>
              ))}
            </div>
          </div>
        )}
        <details className="mt-4 text-[13px]">
          <summary className="cursor-pointer text-mute hover:text-fg">Options</summary>
          <div className="mt-3 space-y-3">
            <div>
              <label htmlFor="import-include" className="block text-[12.5px] text-mute">Only these paths (monorepos), comma-separated globs</label>
              <input id="import-include" value={include} onChange={(e) => setInclude(e.target.value)} placeholder="services/billing/**, packages/agent/**"
                className="mt-1 w-full rounded-lg border border-line bg-panel-2 px-3 py-2 font-mono text-[12.5px] outline-none focus:border-ember/70" />
            </div>
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} className="accent-[#e8592a]" />
              Let a model write one-line descriptions and extra questions
            </label>
            {useLlm && (
              <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_180px]">
                <div>
                  <label htmlFor="import-llm-url" className="block text-[12.5px] text-mute">Model server (empty: the local one)</label>
                  <input id="import-llm-url" value={llmUrl} onChange={(e) => setLlmUrl(e.target.value)} placeholder="https://openrouter.ai/api/v1"
                    className="mt-1 w-full rounded-lg border border-line bg-panel-2 px-3 py-2 font-mono text-[12.5px] outline-none focus:border-ember/70" />
                </div>
                <div>
                  <label htmlFor="import-llm-model" className="block text-[12.5px] text-mute">Model</label>
                  <input id="import-llm-model" value={llmModel} onChange={(e) => setLlmModel(e.target.value)} placeholder="auto"
                    className="mt-1 w-full rounded-lg border border-line bg-panel-2 px-3 py-2 font-mono text-[12.5px] outline-none focus:border-ember/70" />
                </div>
                <p className="text-[12px] text-dim sm:col-span-2">A hosted server uses the key in <code className="font-mono">CRUCIBLE_LLM_API_KEY</code>. Only redacted snippets are sent; the review lists every one.</p>
              </div>
            )}
          </div>
        </details>
        {mode === "path" && path.trim() && (
          <div className="mt-4 rounded-lg border border-line bg-panel-2/40 p-3.5 text-[12.5px]" aria-live="polite">
            {!preview && (previewing || previewed?.key !== previewKey) ? <span className="flex items-center gap-2 text-dim"><Spinner /> Checking the folder…</span> : preview ? (
              <>
                <div className="font-medium text-fg">
                  Will read {preview.files} files{Object.keys(preview.languages).length > 0 && ": "}
                  <span className="font-normal text-mute">{Object.entries(preview.languages).map(([l, n]) => `${n} ${l}`).join(", ")}</span>
                </div>
                <div className="mt-1 text-mute">
                  Skips {[...Object.entries(preview.skipped).map(([why, n]) => `${n} ${why}`), ...(preview.secrets_skipped ? [`${preview.secrets_skipped} secret files (.env, keys)`] : [])].join(" · ") || "nothing"}
                </div>
                <div className={`mt-1 ${preview.hosted ? "text-warn" : "text-mute"}`}>
                  {preview.model ? <>Descriptions by <code className="font-mono">{preview.model.model}</code> at <code className="font-mono">{preview.model.url}</code>{preview.hosted ? " (hosted: redacted snippets leave this machine)" : " (local)"}</>
                    : useLlm ? "No model server answered: descriptions will come from the code only." : "No model: descriptions come from the code only."}
                </div>
              </>
            ) : <span className="text-dim">Can&apos;t preview this folder.</span>}
          </div>
        )}
        {error && <p role="alert" className="mt-4 text-[13px] text-bad">{error}</p>}
        <div className="mt-5">
          <Button onClick={start} disabled={!value.trim() || busy || !canWrite} title={canWrite ? undefined : "Read-only access"}>
            {busy ? <><Spinner /> Starting…</> : <><IconImport className="h-3.5 w-3.5" /> Scan codebase</>}
          </Button>
        </div>
      </Card>
      <Card className="p-5 text-[13px] leading-relaxed text-mute">
        <div className="mb-2 flex items-center gap-2 font-medium text-fg"><IconShield className="h-4 w-4 text-ember" /> What happens</div>
        <ul className="space-y-2">
          <li>The code is <b className="text-fg">read, never run</b>. <code className="font-mono text-[12px]">.env</code> files and secrets are skipped.</li>
          <li>Every finding links to the file and line it came from; anything unproven becomes a question.</li>
          <li>You review and edit everything. Approving writes an <code className="font-mono text-[12px]">agent-tests/</code> folder and smoke-runs it.</li>
        </ul>
        {roots && roots.roots.length > 0 && (
          <div className="mt-4 border-t border-line pt-3 text-[12px] text-dim">This server can read: {roots.roots.join(", ")}</div>
        )}
      </Card>
    </div>
  );
}

// ---------------------------------------------------------------- 2 / 4. progress

function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

const clock = (s: number) => {
  const sec = Math.max(0, Math.floor(s));
  return sec < 60 ? `${sec} s` : `${Math.floor(sec / 60)} min ${String(sec % 60).padStart(2, "0")} s`;
};

/** What the job is doing now, how long it has taken, and (in the smoke run) how far along it is. */
function phaseOf(job: ImportJob, elapsed: number) {
  const msgs = job.progress;
  const last = msgs[msgs.length - 1];
  const smokeAt = msgs.findIndex((p) => p.message.startsWith("Smoke run: one attempt"));
  if (job.status === "applying") {
    const total = (job.discovery?.scenarios ?? []).filter((s) => s.include).length;
    if (smokeAt >= 0) {
      const results = msgs.slice(smokeAt + 1).filter((p) => /^[✓✗]/.test(p.message));
      const done = results.length;
      const per = done ? (results[done - 1].t - msgs[smokeAt].t) / done : null;
      const left = per && total > done ? per * (total - done) - (elapsed - results[done - 1].t) : null;
      return {
        label: `Running test ${Math.min(done + 1, total)} of ${total} against your agent`,
        done, total,
        eta: left && left > 0 ? `about ${clock(left)} left` : done >= total ? "finishing" : "estimating time left after the first test…",
      };
    }
    return { label: last?.message.startsWith("Connection check") ? "Starting the smoke run" : "Writing the tests and checking every connection", done: 0, total, eta: null };
  }
  if (last?.message.startsWith("Asking ")) {
    return { label: "The model is describing the agents and tools (it gives up after 5 minutes and carries on without it)", done: 0, total: 0, eta: null };
  }
  return { label: last?.message ?? "Starting", done: 0, total: 0, eta: null };
}

function Progress({ job, title }: { job: ImportJob; title: string }) {
  const failed = job.status === "failed" || job.status === "apply_failed";
  const running = job.status === "scanning" || job.status === "applying";
  const now = useNow(running);
  const elapsed = now / 1000 - job.started;
  const last = job.progress[job.progress.length - 1];
  const quiet = last ? elapsed - last.t : 0;
  const phase = phaseOf(job, elapsed);
  const logRef = useRef<HTMLOListElement>(null);
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight; // follow the newest line
  }, [job.progress.length]);
  const expect = job.status === "applying"
    ? `Usually 5–10 minutes on a local model: each of the ${phase.total} tests runs once against your agent, and a model grades some of them. You can leave this page; the import keeps going and you can come back to it.`
    : "Reading the code takes seconds. If a model writes the descriptions, add a few minutes on a local model.";
  return (
    <Card className="p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-3">
          {failed ? <span className="flex h-7 w-7 items-center justify-center rounded-full bg-bad/15 text-bad"><IconX className="h-4 w-4" /></span> : <Spinner className="h-5 w-5 text-info" />}
          <div>
            <div className="text-[16px] font-semibold">{title}</div>
            <div className="font-mono text-[12px] text-dim">{job.source}</div>
          </div>
        </div>
        {running && (
          <div className="text-right" aria-live="off">
            <div className="font-mono text-[20px] font-semibold tabular-nums">{clock(elapsed)}</div>
            <div className="text-[11.5px] text-dim">elapsed</div>
          </div>
        )}
      </div>
      {running && (
        <div className="mt-4 rounded-lg border border-info/25 bg-info/[0.05] px-4 py-3">
          <p className="text-[13px] text-mute">{expect}</p>
          <div className="mt-2.5 flex flex-wrap items-center justify-between gap-2 text-[13px]">
            <span className="flex items-center gap-2 font-medium text-fg" role="status">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-info" />{phase.label}
            </span>
            <span className="font-mono text-[12px] text-dim">
              {phase.eta ?? (quiet >= 5 ? `still working · last update ${clock(quiet)} ago` : "working")}
            </span>
          </div>
          {phase.total > 0 && job.status === "applying" && (
            <div className="mt-2.5">
              <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
                <div className="h-full rounded-full bg-info transition-all duration-700" style={{ width: `${Math.max(3, (100 * phase.done) / phase.total)}%` }} />
              </div>
              <div className="mt-1 text-[11.5px] text-dim">{phase.done} of {phase.total} tests done{phase.eta && quiet >= 5 ? ` · last result ${clock(quiet)} ago` : ""}</div>
            </div>
          )}
        </div>
      )}
      <ol ref={logRef} className="mt-4 max-h-80 space-y-1 overflow-y-auto rounded-lg border border-line bg-panel-2/50 p-3 font-mono text-[12px]">
        {job.progress.map((p, i) => (
          <li key={i} className={p.message.startsWith("✗") ? "text-bad" : p.message.startsWith("✓") ? "text-ok" : "text-fg/85"}>
            <span className="mr-2 text-dim">{p.t.toFixed(1)}s</span>{p.message}
          </li>
        ))}
        {running && <li className="text-dim">… {clock(elapsed)}</li>}
      </ol>
      {job.error && <p className="mt-3 text-[13px] text-bad">{job.error}</p>}
    </Card>
  );
}

// ---------------------------------------------------------------- 3. review

function Review({ job, onChange }: { job: ImportJob; onChange: (j: ImportJob) => void }) {
  const d = job.discovery as Discovery;
  const { canWrite } = useProject();
  const [tab, setTab] = useState<Tab>("map");
  const [focus, setFocus] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // the system map's nodes open their card on the matching tab
  function openCard(t: Tab, id: string) {
    setTab(t);
    setFocus(id);
  }
  useEffect(() => {
    if (!focus) return;
    const el = document.getElementById(focus);
    if (!el) return;
    el.scrollIntoView({ block: "center", behavior: "smooth" });
    el.classList.add("ring-2", "ring-ember/60");
    const t = setTimeout(() => el.classList.remove("ring-2", "ring-ember/60"), 1600);
    return () => clearTimeout(t);
  }, [focus, tab]);

  async function patch(body: Record<string, unknown>): Promise<boolean> {
    setSaving(true);
    setError(null);
    try {
      onChange(await api<ImportJob>(`/api/discover/${job.id}`, { method: "PATCH", body: JSON.stringify(body) }));
      return true;
    } catch (e) {
      setError((e as Error).message);
      return false;
    } finally {
      setSaving(false);
    }
  }

  async function approve() {
    setSaving(true);
    try {
      onChange(await api<ImportJob>(`/api/discover/${job.id}/apply`, { method: "POST", body: JSON.stringify({ smoke: true, pull_request: pr }) }));
    } catch (e) {
      setError((e as Error).message);
      setSaving(false);
    }
  }

  const included = d.agents.filter((a) => a.include);
  const open = d.questions.filter((q) => !q.answer);
  const [pr, setPr] = useState(false);
  const scenarios = d.scenarios.filter((s) => s.include);
  const tabs: [Tab, string, number | null][] = [
    ["map", "System map", null], ["agents", "Agents", d.agents.length], ["tools", "Tools", d.tools.length],
    ["questions", "Questions", open.length], ["connection", "How it runs", d.plans.length], ["tests", "Draft tests", scenarios.length],
    ["graph", "Knowledge graph", null],
  ];

  return (
    <>
      <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Summary label="Agents to test" value={included.length} sub={`${d.agents.length} found · ${d.repo.frameworks.join(", ") || "no framework"}`} />
        <Summary label="Tools" value={d.tools.length} sub={`${d.tools.filter((t) => t.effects.includes("destructive")).length} destructive (mocked by default)`} />
        <Summary label="Open questions" value={open.length} sub={open.length ? "answer what you can" : "nothing to clarify"} tone={open.length ? "warn" : "ok"} />
        <Summary label="Draft tests" value={scenarios.length}
          sub={`${coverage(d).tested.length}/${coverage(d).tools.length} tools covered · ${d.repo.files_scanned} files read`} />
      </div>
      <div className="mb-4 flex gap-1 overflow-x-auto border-b border-line [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
        {tabs.map(([k, label, n]) => (
          <button key={k} onClick={() => setTab(k)}
            className={`-mb-px flex shrink-0 items-center gap-2 border-b-2 px-3 py-2.5 text-[13.5px] ${tab === k ? "border-ember text-fg" : "border-transparent text-mute hover:text-fg"}`}>
            {label}{n !== null && <span className={`rounded-full px-1.5 font-mono text-[10.5px] ${k === "questions" && n ? "bg-warn/15 text-warn" : "bg-white/5 text-dim"}`}>{n}</span>}
          </button>
        ))}
      </div>
      {error && <p role="alert" className="mb-3 text-[13px] text-bad">{error}</p>}
      {tab === "map" && <><SystemMap d={d} open={openCard} /><Synthesis d={d} /></>}
      {tab === "agents" && <Agents d={d} patch={patch} disabled={!canWrite || saving} />}
      {tab === "tools" && <Tools d={d} patch={patch} disabled={!canWrite || saving} />}
      {tab === "questions" && <Questions d={d} patch={patch} disabled={!canWrite || saving} />}
      {tab === "connection" && <Connection d={d} patch={patch} disabled={!canWrite || saving} />}
      {tab === "tests" && <Tests d={d} patch={patch} disabled={!canWrite || saving} />}
      {tab === "graph" && <JobGraph jobId={job.id} />}
      <div className="sticky bottom-0 mt-6 flex flex-wrap items-center justify-between gap-3 rounded-xl border border-line bg-ink/90 px-4 py-3 backdrop-blur">
        <div className="text-[13px] text-mute">
          {included.length} agent{included.length === 1 ? "" : "s"} · {scenarios.length} tests will be written to{" "}
          <code className="font-mono text-[12px] text-fg">{d.repo.root.replace(/[\\/]$/, "")}/agent-tests</code>, then smoke-run once each.
          {d.documents.length > 0 && <> RAG tests answer from a snapshot of {d.documents.length} document{d.documents.length === 1 ? "" : "s"} in the repo.</>}
          <label className="mt-1.5 flex items-center gap-2 text-[12.5px]" title="Commits the tests (and accepted code changes) to a new branch from your current commit, pushes it and opens a pull request with the GitHub CLI when it's logged in. Your working tree isn't touched.">
            <input type="checkbox" checked={pr} onChange={(e) => setPr(e.target.checked)} className="accent-[#ff6b35]" disabled={!canWrite || saving} />
            Also open a pull request with the tests (needs a git repository with a remote)
          </label>
        </div>
        <Button onClick={approve} disabled={!canWrite || saving || included.length === 0}>
          {saving ? <Spinner /> : <IconCheck className="h-3.5 w-3.5" />} Looks good: write tests and smoke-run
        </Button>
      </div>
    </>
  );
}

function Summary({ label, value, sub, tone }: { label: string; value: number; sub: string; tone?: "ok" | "warn" }) {
  return (
    <Card className="p-4">
      <div className="text-[12px] text-dim">{label}</div>
      <div className={`mt-0.5 text-[26px] font-semibold tabular-nums ${tone === "warn" ? "text-warn" : ""}`}>{value}</div>
      <div className="truncate text-[12px] text-mute">{sub}</div>
    </Card>
  );
}

function Evidence({ d, ids }: { d: Discovery; ids: string[] }) {
  const seen = new Set<string>();
  const ev = ids.flatMap((id) => d.facts[id]?.evidence ?? []).filter((e) => {
    const key = `${e.file}:${e.line}`;
    return !seen.has(key) && seen.add(key);
  });
  if (!ev.length) return null;
  const where = ev.map((e) => `${e.file}:${e.line}`);
  return (
    <details className="mt-2 text-[12px]">
      <summary className="cursor-pointer break-all font-mono text-dim hover:text-fg">
        {where.slice(0, 3).join(" · ")}{where.length > 3 ? ` · +${where.length - 3} more` : ""}
      </summary>
      <div className="mt-2 space-y-2">
        {ev.map((e) => (
          <div key={`${e.file}:${e.line}`}>
            <div className="font-mono text-[11.5px] text-dim">{e.file}:{e.line}</div>
            {e.snippet && <pre className="code mt-1 max-h-48 overflow-auto whitespace-pre-wrap rounded-lg bg-panel-2 p-3 text-[11.5px] text-mute">{e.snippet}</pre>}
          </div>
        ))}
      </div>
    </details>
  );
}

function Synthesis({ d }: { d: Discovery }) {
  const s = d.synthesis;
  if (!s.used && !s.error) return null;
  return (
    <Card className="mt-4 p-4 text-[12.5px] text-mute">
      {s.error ? <>The model step was skipped ({s.error}); everything above comes from the code alone.</> : (
        <details>
          <summary className="cursor-pointer">
            Descriptions by <code className="font-mono text-fg">{s.model}</code>{s.base_url && <> at <code className="font-mono">{s.base_url}</code></>}:
            {" "}{s.sent?.length ?? 0} redacted snippets sent in {s.requests ?? 1} request{(s.requests ?? 1) === 1 ? "" : "s"}
            {s.cached ? `, ${s.cached} answered from the cache` : ""}. Show what was sent
          </summary>
          <ul className="mt-2 max-h-48 space-y-0.5 overflow-auto font-mono text-[11.5px] text-dim">
            {(s.sent ?? []).map((x) => <li key={`${x.fact}${x.file}${x.line}`}>{x.file}:{x.line}</li>)}
          </ul>
        </details>
      )}
    </Card>
  );
}

function SystemMap({ d, open }: { d: Discovery; open: (t: Tab, id: string) => void }) {
  const agents = d.agents.filter((a) => a.include);
  if (!agents.length) return <Card><Empty icon={<IconImport />} title="No agents selected">Include an agent on the Agents tab.</Empty></Card>;
  const services = [...new Set(agents.map((a) => a.service ?? ""))];
  return (
    <div className="space-y-4">
      {services.map((svc) => (
        <div key={svc || "root"} className="space-y-4">
          {svc && <div className="pt-1 font-mono text-[12px] uppercase tracking-[0.12em] text-dim">{svc}</div>}
          {agents.filter((a) => (a.service ?? "") === svc).map((a) => <MapRow key={a.id} d={d} a={a} open={open} />)}
        </div>
      ))}
      <p className="text-[12px] text-dim">Click an agent or a tool to open its card.</p>
      <div className="flex flex-wrap gap-3 text-[11.5px] text-dim">
        {(Object.keys(EFFECT_TONE) as Effect[]).map((e) => <span key={e} className="flex items-center gap-1.5"><Badge tone={EFFECT_TONE[e]}>{e}</Badge></span>)}
      </div>
    </div>
  );
}

function MapRow({ d, a, open }: { d: Discovery; a: DAgent; open: (t: Tab, id: string) => void }) {
  const subs = a.subagents.map((s) => d.agents.find((x) => x.id === s)).filter(Boolean) as DAgent[];
  const tools = [...a.tools, ...subs.flatMap((s) => s.tools)].map((n) => d.tools.find((t) => t.name === n)).filter(Boolean) as DTool[];
  return (
          <Card className="p-5">
            <div className="grid gap-4 lg:grid-cols-[230px_minmax(0,1fr)_200px] lg:items-start">
              <button type="button" onClick={() => open("agents", `agent-${a.id}`)}
                className="rounded-xl border border-ember/50 bg-ember/[0.07] p-3 text-left transition-colors hover:bg-ember/[0.12]">
                <div className="text-[14px] font-semibold">{a.name}</div>
                <div className="mt-0.5 text-[12px] text-mute">{a.framework} · {a.entrypoint.kind === "http" ? a.entrypoint.route : a.entrypoint.object ?? a.entrypoint.command ?? "start: ?"}</div>
                {a.purpose && <p className="mt-2 text-[12.5px] leading-snug text-fg/85">{a.purpose}</p>}
                {subs.length > 0 && <div className="mt-2 text-[12px] text-mute">hands work to {subs.map((s) => s.name).join(", ")}</div>}
                {a.memory && <div className="mt-1 text-[12px] text-mute">remembers via {a.memory}</div>}
              </button>
              <div className="min-w-0">
                <div className="mb-1.5 text-[11px] uppercase tracking-[0.12em] text-dim">Tools</div>
                <div className="flex flex-wrap gap-1.5">
                  {tools.map((t) => {
                    const worst = (["destructive", "writes data", "reads untrusted text", "external call", "read-only"] as Effect[]).find((e) => t.effects.includes(e));
                    const tone = worst ? EFFECT_TONE[worst] : "mute";
                    return (
                      <button type="button" key={t.name} title={t.effects.join(", ") || "effects unknown"} onClick={() => open("tools", `tool-${t.name}`)}
                        className={`rounded-lg border px-2 py-1 font-mono text-[11.5px] hover:bg-white/[0.04] ${tone === "bad" ? "border-bad/50 text-bad" : tone === "warn" ? "border-warn/50 text-warn" : tone === "ember" ? "border-ember/50 text-ember" : tone === "info" ? "border-info/40 text-info" : "border-line text-mute"}`}>
                        {t.server ? `${t.server}/` : ""}{t.name}
                      </button>
                    );
                  })}
                  {!tools.length && <span className="text-[12.5px] text-dim">no tools</span>}
                </div>
              </div>
              <div>
                <div className="mb-1.5 text-[11px] uppercase tracking-[0.12em] text-dim">Touches</div>
                <ul className="space-y-1 text-[12.5px]">
                  {a.datastores.map((s) => <li key={s} className="flex items-center gap-1.5"><IconServer className="h-3.5 w-3.5 text-dim" /> database <code className="font-mono">{s}</code></li>)}
                  {a.external_apis.map((s) => <li key={s} className="flex items-center gap-1.5"><IconGit className="h-3.5 w-3.5 text-dim" /> {d.external_apis.find((x) => x.id === s)?.kind === "queue" ? "queue" : "API"} <code className="font-mono">{s}</code></li>)}
                  {a.mcp_servers.map((s) => <li key={s} className="flex items-center gap-1.5"><IconServer className="h-3.5 w-3.5 text-dim" /> MCP <code className="font-mono">{s}</code></li>)}
                  {!a.datastores.length && !a.external_apis.length && !a.mcp_servers.length && <li className="text-dim">nothing outside the process</li>}
                </ul>
              </div>
            </div>
          </Card>
  );
}

function Agents({ d, patch, disabled }: { d: Discovery; patch: (b: Record<string, unknown>) => void; disabled: boolean }) {
  return (
    <div className="space-y-3">
      {d.agents.map((a) => (
        <Card key={a.id} id={`agent-${a.id}`} className={`p-5 transition-shadow ${a.include ? "" : "opacity-70"}`}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <input aria-label={`Name of ${a.id}`} defaultValue={a.name} disabled={disabled}
                onBlur={(e) => e.target.value !== a.name && patch({ agents: { [a.id]: { name: e.target.value } } })}
                className="w-full max-w-md rounded-md bg-transparent text-[16px] font-semibold outline-none focus:bg-panel-2 focus:px-2" />
              <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[12px]">
                <Badge>{a.framework}</Badge><Badge>{a.language}</Badge>
                <Badge tone={a.confidence === "high" ? "ok" : a.confidence === "medium" ? "info" : "warn"}>{a.confidence} confidence</Badge>
              </div>
            </div>
            <label className="flex items-center gap-2 text-[13px]">
              <input type="checkbox" checked={a.include} disabled={disabled} onChange={(e) => patch({ agents: { [a.id]: { include: e.target.checked } } })} className="accent-[#e8592a]" />
              Test this agent
            </label>
          </div>
          <textarea aria-label={`Purpose of ${a.id}`} defaultValue={a.purpose} disabled={disabled} rows={2} placeholder="What does this agent do?"
            onBlur={(e) => e.target.value !== a.purpose && patch({ agents: { [a.id]: { purpose: e.target.value } } })}
            className="mt-3 w-full resize-y rounded-lg border border-line bg-panel-2/60 px-3 py-2 text-[13.5px] outline-none focus:border-ember/60" />
          <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-[12.5px] sm:grid-cols-2">
            <Row k="Started via">{a.entrypoint.kind === "code" ? <code className="font-mono">{a.entrypoint.module}.{a.entrypoint.object}</code> : a.entrypoint.route ?? a.entrypoint.command ?? <span className="text-warn">unknown</span>}</Row>
            <Row k="Model">{a.model.value ?? (a.model.env ? `$${a.model.env}` : <span className="text-dim">not found (tests force one anyway)</span>)}</Row>
            <Row k="System prompt">{a.system_prompt.file ?? (a.system_prompt.text ? `“${a.system_prompt.text.slice(0, 70)}…”` : <span className="text-dim">not found</span>)}</Row>
            <Row k="Tools">{a.tools.length ? a.tools.join(", ") : <span className="text-dim">none</span>}</Row>
            {a.subagents.length > 0 && <Row k="Hands work to">{a.subagents.map((s) => d.agents.find((x) => x.id === s)?.name ?? s).join(", ")}</Row>}
            {a.mcp_servers.length > 0 && <Row k="MCP servers">{a.mcp_servers.join(", ")}</Row>}
            <Row k="Memory / state">{a.memory ?? <span className="text-dim">none found (each conversation starts fresh)</span>}</Row>
            {(a.datastores.length > 0 || a.external_apis.length > 0) && <Row k="Touches">{[...a.datastores.map((s) => `database ${s}`), ...a.external_apis].join(", ")}</Row>}
            {a.service && <Row k="Service">{a.service}</Row>}
          </dl>
          {a.notes.map((n) => <p key={n} className="mt-2 text-[12.5px] text-mute">• <Ticks text={n} /></p>)}
          <Evidence d={d} ids={a.evidence} />
        </Card>
      ))}
    </div>
  );
}

/** Text with `backticked` names shown as code. */
function Ticks({ text }: { text: string }) {
  return <>{text.split(/`([^`]+)`/).map((part, i) => (i % 2 ? <code key={i} className="font-mono text-[0.95em] text-fg">{part}</code> : part))}</>;
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-wrap gap-x-2 sm:flex-nowrap">
      <dt className="min-w-28 max-w-full break-all text-dim sm:w-44 sm:shrink-0">{k}</dt>
      <dd className="min-w-0 break-words">{children}</dd>
    </div>
  );
}

function Tools({ d, patch, disabled }: { d: Discovery; patch: (b: Record<string, unknown>) => void; disabled: boolean }) {
  return (
    <Card>
      <CardHeader title="Tools" sub="Click a badge to correct what a tool does. Destructive tools are mocked in the drafted tests until you change that." />
      <ul className="divide-y divide-line/70">
        {d.tools.map((t) => (
          <li key={t.name} id={`tool-${t.name}`} className="scroll-mt-24 rounded-lg px-5 py-3.5 transition-shadow">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="min-w-0">
                <span className="font-mono text-[13.5px] font-semibold">{t.name}</span>
                <span className="ml-2 text-[12px] text-dim">{t.server ? `MCP · ${t.server}` : t.kind}{t.agents.length ? ` · used by ${t.agents.join(", ")}` : " · not used by an agent"}</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {EFFECTS.map((e) => {
                  const on = t.effects.includes(e);
                  return (
                    <button key={e} disabled={disabled} aria-pressed={on}
                      onClick={() => patch({ tools: { [t.name]: { effects: on ? t.effects.filter((x) => x !== e) : [...t.effects, e] } } })}
                      className={`rounded-full px-2 py-0.5 font-mono text-[10.5px] transition-opacity ${on ? `${toneClass(EFFECT_TONE[e])}` : "bg-white/[0.03] text-dim opacity-60 hover:opacity-100"}`}>
                      {e}
                    </button>
                  );
                })}
              </div>
            </div>
            {t.description && <p className="mt-1 text-[13px] text-mute">{t.description}</p>}
            <dl className="mt-2 grid gap-x-6 gap-y-1 text-[12px] sm:grid-cols-2">
              <Row k="Inputs">{Object.keys(t.params).length ? <code className="font-mono">{Object.entries(t.params).map(([p, ty]) => `${p}: ${ty}`).join(", ")}</code> : <span className="text-dim">none found</span>}</Row>
              {t.touches.length > 0 && <Row k="Touches">{t.touches.map((x) => x.replace(":", " ")).join(", ")}</Row>}
              {t.sql_writes.length > 0 && <Row k="Writes"><code className="font-mono">{t.sql_writes.join("; ")}</code></Row>}
              {t.files.length > 0 && <Row k="Files">{t.files.join(" and ")} (tests run in a fresh copy of the repository)</Row>}
            </dl>
            {(t.effects.includes("destructive") || t.effects.includes("writes data")) && t.kind !== "builtin" && (() => {
              const mocked = t.mock ?? t.effects.includes("destructive");
              return (
                <label className="mt-2 flex items-start gap-2 text-[12.5px]">
                  <input type="checkbox" checked={mocked} disabled={disabled} className="mt-0.5 accent-[#e8592a]"
                    onChange={(e) => patch({ tools: { [t.name]: { mock: e.target.checked } } })} />
                  <span>
                    Mock it in tests <span className="text-dim">
                      {mocked ? "(a canned reply; nothing real changes)" : "(it runs against the test fixtures; drafts check what changed)"}
                    </span>
                  </span>
                </label>
              );
            })()}
            <Evidence d={d} ids={t.evidence} />
          </li>
        ))}
      </ul>
    </Card>
  );
}

function toneClass(t: "ok" | "warn" | "bad" | "info" | "ember"): string {
  return { ok: "bg-ok/12 text-ok", warn: "bg-warn/12 text-warn", bad: "bg-bad/12 text-bad", info: "bg-info/12 text-info", ember: "bg-ember/12 text-ember" }[t];
}

function Questions({ d, patch, disabled }: { d: Discovery; patch: (b: Record<string, unknown>) => void; disabled: boolean }) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  if (!d.questions.length) return <Card><Empty icon={<IconCheck />} title="No open questions">Everything was found in the code.</Empty></Card>;
  return (
    <div className="space-y-3">
      {d.questions.map((q) => (
        <Card key={q.id} className="p-5">
          <div className="flex items-start gap-3">
            <span className={`mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full ${q.answer ? "bg-ok/15 text-ok" : "bg-warn/15 text-warn"}`}>
              {q.answer ? <IconCheck className="h-3.5 w-3.5" /> : "?"}
            </span>
            <div className="min-w-0 flex-1">
              <p className="text-[14px] font-medium"><Ticks text={q.text} /></p>
              {q.answer && <p className="mt-1 text-[13px] text-ok">Answered: {q.answer}</p>}
              <div className="mt-3 flex flex-wrap items-center gap-2">
                {q.options.map((o) => (
                  <button key={o} disabled={disabled} onClick={() => patch({ questions: { [q.id]: o } })}
                    className={`rounded-full border px-3 py-1 text-[12.5px] ${q.answer === o ? "border-ember/60 bg-ember/10" : "border-line text-mute hover:text-fg"}`}>{o}</button>
                ))}
                {!q.options.length && (
                  <>
                    <input aria-label="Answer" value={drafts[q.id] ?? q.answer ?? ""} placeholder={q.suggested ?? "your answer"} disabled={disabled}
                      onChange={(e) => setDrafts({ ...drafts, [q.id]: e.target.value })}
                      className="min-w-0 flex-1 rounded-lg border border-line bg-panel-2 px-3 py-1.5 font-mono text-[12.5px] outline-none focus:border-ember/60" />
                    <Button variant="secondary" disabled={disabled || !(drafts[q.id] ?? q.suggested)} onClick={() => patch({ questions: { [q.id]: drafts[q.id] ?? q.suggested ?? "" } })}>Save</Button>
                  </>
                )}
              </div>
              <Evidence d={d} ids={q.evidence} />
            </div>
          </div>
        </Card>
      ))}
    </div>
  );
}

function Diff({ title, removed, added, note }: { title: string; removed: string[]; added: string[]; note?: string }) {
  return (
    <div className="overflow-hidden rounded-xl border border-line bg-panel-2/60">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-2 font-mono text-[11.5px] text-dim">
        <span className="break-all">{title}</span>{note && <span>{note}</span>}
      </div>
      <pre className="code max-h-96 overflow-auto px-4 py-3 text-[12px]">
        {removed.map((l, i) => <div key={`r${i}`} className="whitespace-pre-wrap break-words text-bad"><span className="select-none text-bad/70">- </span>{l}</div>)}
        {added.map((l, i) => <div key={`a${i}`} className="whitespace-pre-wrap break-words text-ok"><span className="select-none text-ok/70">+ </span>{l}</div>)}
      </pre>
    </div>
  );
}

function Connection({ d, patch, disabled }: { d: Discovery; patch: (b: Record<string, unknown>) => Promise<boolean>; disabled: boolean }) {
  if (!d.plans.length) return <Card><Empty icon={<IconServer />} title="No agents selected">Include an agent on the Agents tab.</Empty></Card>;
  return (
    <div className="space-y-4">
      {d.plans.map((p) => {
        const a = d.agents.find((x) => x.id === p.agent);
        return (
          <Card key={p.agent} className="p-5">
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[15px] font-semibold">{a?.name ?? p.agent}</span>
              <Badge tone={p.strategy === "manual" ? "warn" : "ember"}>{p.strategy}</Badge>
            </div>
            <p className="mt-1.5 text-[13.5px] text-mute"><Ticks text={p.why} /></p>
            {p.warnings.length > 0 && (
              <ul className="mt-3 space-y-1.5">
                {p.warnings.map((w) => <li key={w} className="rounded-lg border border-warn/30 bg-warn/[0.06] px-3 py-2 text-[12.5px] text-fg/90"><Ticks text={w} /></li>)}
              </ul>
            )}
            <dl className="mt-3 grid gap-x-6 gap-y-1.5 text-[12.5px] sm:grid-cols-2">
              <Row k="Command"><code className="font-mono">{p.command}</code></Row>
              <Row k="Settings it reads">{p.env_needed.length ? p.env_needed.join(", ") : <span className="text-dim">none found</span>}</Row>
              {Object.entries(p.env_map).map(([k, v]) => <Row key={k} k={k}><span className="text-mute">→ </span><code className="font-mono">{v}</code></Row>)}
            </dl>
            {p.fixes.length > 0 && (
              <div className="mt-4 space-y-3">
                <div className="text-[13px] font-medium">Suggested change to your code <span className="font-normal text-dim">(applied only if you accept it)</span></div>
                {p.fixes.map((fx) => (
                  <div key={fx.id} className="space-y-2">
                    <Diff title={`${fx.file}:${fx.line}`} removed={[fx.old]} added={[...(fx.add_import ? [`${fx.add_import}   # at the top of the file`] : []), fx.new]} />
                    <label className="flex items-start gap-2 text-[12.5px]">
                      <input type="checkbox" checked={fx.accept} disabled={disabled} className="mt-0.5 accent-[#e8592a]"
                        onChange={(e) => patch({ fixes: { [fx.id]: e.target.checked } })} />
                      <span>Apply this change when I approve. <span className="text-dim">{fx.why}</span></span>
                    </label>
                  </div>
                ))}
              </div>
            )}
            {p.adapter_code && (
              <div className="mt-4">
                <Diff title={p.adapter_file ?? "adapter"} note="new file" removed={[]} added={p.adapter_code.replace(/\n$/, "").split("\n")} />
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

/** Tools of the included agents that at least one included draft mentions (same rule as `crucible discover --check`). */
function coverage(d: Discovery) {
  const texts = d.scenarios.filter((s) => s.include).map((s) => s.yaml);
  const tools = [...new Set(d.agents.filter((a) => a.include).flatMap((a) => a.tools))];
  const tested = tools.filter((t) => texts.some((x) => x.includes(` ${t}`) || x.includes(`: ${t}\n`) || x.includes(`tool: ${t}`)));
  return { tools, tested, untested: tools.filter((t) => !tested.includes(t)) };
}

function Tests({ d, patch, disabled }: { d: Discovery; patch: (b: Record<string, unknown>) => Promise<boolean>; disabled: boolean }) {
  const byAgent = useMemo(() => {
    const m: Record<string, typeof d.scenarios> = {};
    for (const s of d.scenarios) (m[s.agent] ??= []).push(s);
    return m;
  }, [d]);
  const cov = coverage(d);
  const pct = cov.tools.length ? Math.round((cov.tested.length / cov.tools.length) * 100) : 100;
  return (
    <div className="space-y-5">
      <Card className="p-4">
        <div className="flex flex-wrap items-baseline justify-between gap-2 text-[13px]">
          <span className="font-medium">Coverage: {cov.tested.length} of {cov.tools.length} tools have at least one test</span>
          <span className="font-mono text-[12px] text-dim">{pct}%</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-white/[0.06]" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100} aria-label="Tool coverage">
          <div className={`h-full rounded-full ${pct === 100 ? "bg-ok" : "bg-warn"}`} style={{ width: `${pct}%` }} />
        </div>
        {cov.untested.length > 0 && <p className="mt-2 text-[12.5px] text-mute">No test yet: {cov.untested.map((t) => <code key={t} className="mr-1.5 font-mono">{t}</code>)}</p>}
      </Card>
      {Object.entries(byAgent).map(([agent, list]) => (
        <Card key={agent}>
          <CardHeader title={d.agents.find((a) => a.id === agent)?.name ?? agent} sub={`${list.filter((s) => s.include).length} of ${list.length} drafts included`} />
          <ul className="divide-y divide-line/70">
            {list.map((s) => (
              <li key={s.id} className="px-5 py-3">
                <div className="flex items-start gap-3">
                  <input type="checkbox" aria-label={`Include ${s.id}`} checked={s.include} disabled={disabled}
                    onChange={(e) => patch({ scenarios: { [s.id]: { include: e.target.checked } } })} className="mt-1 accent-[#e8592a]" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 font-mono text-[13px]">{s.id}{s.edited && <Badge tone="info">edited</Badge>}</div>
                    <p className="text-[12.5px] text-mute"><Ticks text={s.reason} /></p>
                    <ScenarioYaml agent={agent} s={s} patch={patch} disabled={disabled} />
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </Card>
      ))}
    </div>
  );
}

function ScenarioYaml({ agent, s, patch, disabled }: {
  agent: string; s: Discovery["scenarios"][number]; patch: (b: Record<string, unknown>) => Promise<boolean>; disabled: boolean;
}) {
  const [draft, setDraft] = useState<string | null>(null);
  return (
    <details className="mt-1.5">
      <summary className="cursor-pointer text-[12px] text-dim hover:text-fg">YAML</summary>
      {draft === null ? (
        <div className="mt-2 space-y-2">
          <Code title={`scenarios/${agent}/${s.id}.yaml`} code={s.yaml} small />
          <Button variant="secondary" disabled={disabled} onClick={() => setDraft(s.yaml)}>Edit</Button>
        </div>
      ) : (
        <div className="mt-2 space-y-2">
          <textarea aria-label={`YAML of ${s.id}`} value={draft} onChange={(e) => setDraft(e.target.value)} spellCheck={false}
            rows={Math.min(24, draft.split("\n").length + 1)}
            className="w-full resize-y rounded-lg border border-line bg-panel-2 px-3 py-2 font-mono text-[12px] outline-none focus:border-ember/60" />
          <div className="flex flex-wrap gap-2">
            <Button disabled={disabled || draft === s.yaml} onClick={async () => {
              if (await patch({ scenarios: { [s.id]: { yaml: draft } } })) setDraft(null);
            }}>Save</Button>
            <Button variant="secondary" onClick={() => setDraft(null)}>Cancel</Button>
          </div>
        </div>
      )}
    </details>
  );
}

// ---------------------------------------------------------------- 5. results

function JobGraph({ jobId }: { jobId: string }) {
  useGraphLinks();
  return (
    <div className="card overflow-hidden">
      <p className="border-b border-line px-5 py-3 text-[13px] text-mute">
        What the scan found, as a graph: files, how they import each other, and every agent, tool and MCP server. Click
        one to see everywhere it&apos;s used. Approving writes it into the repository as <code className="font-mono text-[12px]">agent-tests/knowledge-graph.html</code>.
      </p>
      <iframe src={`${API}/api/discover/${jobId}/graph.html`} title="Knowledge graph of the scanned code" className="block h-[66vh] min-h-[420px] w-full border-0 bg-ink" />
    </div>
  );
}

function Results({ job, onChange }: { job: ImportJob; onChange: (j: ImportJob) => void }) {
  const r = job.result!;
  const { canWrite } = useProject();
  const [adding, setAdding] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  async function addTool(agent: string, tool: string) {
    setAdding(tool);
    setAddError(null);
    try {
      onChange(await api<ImportJob>(`/api/discover/${job.id}/tools`, { method: "POST", body: JSON.stringify({ agent, tool }) }));
    } catch (e) {
      setAddError((e as Error).message);
      setAdding(null);
    }
  }
  const pr = r.pull_request;
  const rep = r.reality;
  const d = job.discovery!;
  const { switchProject } = useProject();
  const nAgents = r.validate.agents.length;
  return (
    <div className="space-y-5">
      {r.project && (
        <Card className="flex flex-wrap items-center justify-between gap-4 border-ember/40 bg-ember/[0.05] p-5">
          <div className="min-w-0">
            <div className="text-[15px] font-semibold">Your {nAgents} agent{nAgents === 1 ? " is" : "s are"} now a project in this dashboard</div>
            <p className="mt-0.5 text-[13px] text-mute">Switch to it to see each agent, run its tests, and compare runs over time. Switch back any time from the sidebar.</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={() => switchProject(r.project!, "/dashboard/agents/")}>See the agents</Button>
            <Button onClick={() => switchProject(r.project!, "/dashboard/")}>Open the project <IconArrow className="h-3.5 w-3.5" /></Button>
          </div>
        </Card>
      )}
      <Card className={`p-5 ${rep && !rep.ok ? "border-warn/40" : "border-ok/30"}`}>
        <div className="flex items-start gap-3">
          <span className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${rep && !rep.ok ? "bg-warn/15 text-warn" : "bg-ok/15 text-ok"}`}>
            {rep && !rep.ok ? "!" : <IconCheck className="h-4 w-4" />}
          </span>
          <div>
            <div className="text-[16px] font-semibold">
              {rep ? `Smoke run: ${rep.passed} of ${rep.episodes} scenarios passed${rep.errors ? `, ${rep.errors} errors` : ""}` : "Tests written"}
            </div>
            <p className="mt-1 text-[13.5px] text-mute">
              {r.files.length} files written to <code className="font-mono text-[12.5px] text-fg">{r.out}</code>.
              {rep && (rep.ok ? " What the agents did matches what was found." : " Some things didn't match what was found; see below.")}
              {rep && rep.passed < rep.episodes && " Failed scenarios are about the agent's behaviour: read why below before treating them as broken tests."}
            </p>
          </div>
        </div>
      </Card>
      {addError && <Card className="border-bad/40 p-4 text-[13px] text-bad">{addError}</Card>}
      {pr && (
        <Card className={`p-5 ${pr.error ? "border-bad/40" : "border-info/30"}`}>
          <div className="text-[14px] font-semibold">{pr.error ? "The pull request wasn't opened" : pr.pr_url ? "Pull request opened" : `Branch ${pr.branch} ${pr.pushed ? "pushed" : "created"}`}</div>
          {pr.error ? <p className="mt-1 text-[13px] text-bad">{pr.error}</p> : (
            <div className="mt-1 space-y-1 text-[13px] text-mute">
              <p>{pr.files?.length} files on <code className="font-mono text-[12px] text-fg">{pr.branch}</code> (commit {pr.commit}), on top of {pr.base}.</p>
              {(pr.pr_url || pr.compare_url) && <p><a href={pr.pr_url ?? pr.compare_url ?? undefined} target="_blank" rel="noreferrer" className="text-ember">{pr.pr_url ? "Open the pull request" : "Open a pull request"} →</a></p>}
              {pr.note && <p className="text-[12.5px] text-dim">{pr.note}</p>}
            </div>
          )}
        </Card>
      )}
      {(r.connection || (r.code_changes && r.code_changes.length > 0)) && (
        <Card>
          <CardHeader title="Before the smoke run" sub="Connection check: the model server, every MCP server and every agent's start command." />
          <ul className="divide-y divide-line/70 text-[13px]">
            {(r.code_changes ?? []).map((c) => (
              <li key={c} className="flex flex-wrap items-center gap-2 px-5 py-2.5"><Badge tone="info">code change</Badge> applied at <code className="font-mono text-[12.5px]">{c}</code></li>
            ))}
            {(r.connection ?? []).map((c) => (
              <li key={c.id} className="flex flex-wrap items-start gap-2 px-5 py-2.5">
                <Badge tone={c.ok ? "ok" : "bad"}>{c.ok ? "ok" : "failed"}</Badge>
                <span className="font-mono text-[12.5px]">{c.id}</span>
                <span className="min-w-0 break-words text-mute"><Ticks text={c.detail} /></span>
              </li>
            ))}
          </ul>
        </Card>
      )}
      {rep && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <CardHeader title="Discovery vs reality" sub="What the smoke run actually observed, per agent." />
            <ul className="divide-y divide-line/70">
              {d.agents.filter((a) => a.include).map((a) => {
                const seen = rep.observed_tools[a.id] ?? {};
                return (
                  <li key={a.id} className="px-5 py-3 text-[13px]">
                    <div className="font-medium">{a.name} <span className="text-dim">· ran on {(rep.models[a.id] ?? []).join(", ") || "no model calls"}
                      {(rep.requested_models?.[a.id] ?? []).length > 0 && ` · its code asks for ${rep.requested_models![a.id].join(", ")}`}</span></div>
                    <div className="mt-1.5 flex flex-wrap gap-1.5">
                      {a.tools.map((t) => (
                        <span key={t} className={`rounded-md px-2 py-0.5 font-mono text-[11.5px] ${seen[t] ? "bg-ok/12 text-ok" : "bg-white/5 text-dim"}`} title={seen[t] ? `called ${seen[t]}x` : "never called"}>
                          {seen[t] ? "✓" : "·"} {t}
                        </span>
                      ))}
                    </div>
                  </li>
                );
              })}
            </ul>
          </Card>
          <Card>
            <CardHeader title={`Findings (${rep.findings.length})`} sub="Mismatches and errors, with what to do." />
            {rep.findings.length === 0 ? <div className="px-5 py-6 text-[13px] text-ok">None. Every predicted tool was used and nothing failed.</div> : (
              <ul className="divide-y divide-line/70">
                {rep.findings.map((f, i) => (
                  <li key={i} className="px-5 py-3 text-[13px]">
                    <Badge tone={f.kind.includes("error") ? "bad" : "warn"}>{f.kind.replace(/_/g, " ")}</Badge>
                    <p className="mt-1.5 break-words"><Ticks text={f.detail} /></p>
                    <p className="text-[12.5px] text-mute"><Ticks text={f.action} /></p>
                    {f.kind === "unexpected_tool" && f.agent && f.tool && canWrite && (
                      <div className="mt-2">
                        <Button variant="secondary" onClick={() => addTool(f.agent!, f.tool!)} disabled={adding !== null}>
                          {adding === f.tool ? <Spinner /> : null} Add {f.tool} to the map
                        </Button>
                        <span className="ml-2 text-[12px] text-dim">then review and approve again to write its tests</span>
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      )}
      {rep?.scenarios && rep.scenarios.length > 0 && (
        <Card>
          <CardHeader title="Scenarios" sub="One attempt each. A failure shows which check caught it." />
          <ul className="divide-y divide-line/70">
            {rep.scenarios.map((s) => (
              <li key={s.scenario} className="px-5 py-3 text-[13px]">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={s.passed ? "ok" : "bad"}>{s.passed ? "passed" : "failed"}</Badge>
                  <span className="break-all font-mono text-[12.5px]">{s.scenario}</span>
                </div>
                {s.why && <p className="mt-1 text-[12.5px] text-mute"><Ticks text={s.why} /></p>}
                {s.error && <p className="mt-1 break-words text-[12.5px] text-bad">{s.error}</p>}
                {s.failed.map((c, i) => (
                  <p key={i} className="mt-1 break-words text-[12.5px]">
                    <code className="font-mono text-bad">{c.check}</code> <span className="text-mute">{c.detail}</span>
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card className="p-5">
        <div className="mb-3 text-[14px] font-semibold">Next</div>
        <p className="mb-3 text-[13px] text-mute">Run a baseline from <b className="text-fg">Runs</b> in the new project, or from the terminal:</p>
        <Code title="terminal" code={`cd ${r.out}\ncrucible run --label baseline -k 3      # a baseline to compare changes against`} />
        <p className="mt-3 text-[12.5px] text-dim">
          <IconRefresh className="mr-1 inline h-3.5 w-3.5" />Keep it current in CI with <code className="font-mono">crucible discover . --check</code>: it fails when a new agent or a destructive tool has no tests.
        </p>
      </Card>
    </div>
  );
}
