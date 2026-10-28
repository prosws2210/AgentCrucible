"use client";

import { useState } from "react";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { Grade } from "@/components/app/bits";
import { useAudits, useResource } from "@/components/app/hooks";
import { IconServer, IconShield } from "@/components/Icons";
import { Badge, Button, Card, CardHeader, Empty, Spinner } from "@/components/ui";
import { api, type Audit, type Config } from "@/lib/api";
import { ago } from "@/lib/format";

const SEV: Record<string, number> = { critical: 0, high: 1, medium: 2, low: 3, info: 4 };
const SEV_TONE: Record<string, "bad" | "ember" | "warn" | "mute"> = { critical: "bad", high: "ember", medium: "warn", low: "mute", info: "mute" };
const SUITES: [string, string][] = [
  ["conformance", "Speaks the MCP protocol correctly"],
  ["tool_quality", "Tool names and descriptions a model can understand"],
  ["robustness", "Survives bad input (fuzzing)"],
  ["security", "SQL injection, path traversal, SSRF"],
  ["behavioral", "A model picks the right tool"],
  ["performance", "Latency under concurrent calls"],
];

export default function ServersPage() {
  const { project } = useProject();
  const audits = useAudits();
  const cfg = useResource<Config>("/api/config");

  return (
    <>
      <PageHeader
        title="MCP servers"
        sub="The tool servers your agent uses, behind a recording proxy. Local servers are started fresh for every episode; remote ones are reached by URL. An audit tests a server on its own, before an agent ever touches it."
      />
      {project.mcp_servers.length === 0 ? (
        <Card><Empty icon={<IconServer />} title="No MCP servers configured">Add them under <code className="font-mono">mcp_servers</code> in crucible.yaml.</Empty></Card>
      ) : (
        <div className="space-y-5">
          {project.mcp_servers.map((name) => (
            <ServerCard key={name} name={name} spec={cfg.data?.mcp_servers.find((m) => m.name === name)}
              audits={(audits.data ?? []).filter((a) => a.server === name)} onAudited={audits.reload} />
          ))}
        </div>
      )}
      <Card className="mt-6">
        <CardHeader title="What an audit checks" sub="A critical finding caps the grade at D, whatever the average." />
        <div className="grid gap-px bg-line sm:grid-cols-2 lg:grid-cols-3">
          {SUITES.map(([k, v]) => (
            <div key={k} className="bg-ink p-4">
              <div className="font-mono text-[12px] text-ember">{k.replace("_", " ")}</div>
              <div className="mt-1 text-[13px] text-mute">{v}</div>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}

function ServerCard({ name, spec, audits, onAudited }: { name: string; spec?: Config["mcp_servers"][number]; audits: Audit[]; onAudited: () => void }) {
  const { project, canWrite } = useProject();
  const [latest, setLatest] = useState<Audit | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const shown = latest ?? null;
  const last = audits[0];

  async function load(id: number) {
    setLatest(await api<Audit>(`/api/audits/${id}`));
  }
  async function run() {
    setBusy(true);
    setError(null);
    try {
      const a = await api<Audit>("/api/audits", { method: "POST", body: JSON.stringify({ server: name, fixture: project.fixtures[0] ?? null }) });
      setLatest(a);
      onAudited();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const report = shown?.report;
  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-4 border-b border-line px-5 py-4">
        <div className="flex min-w-0 items-center gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-line bg-panel-2 text-mute"><IconServer /></span>
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <span className="font-mono text-[15px] font-semibold">{name}</span>
              {spec?.remote && <Badge tone="info">remote</Badge>}
            </div>
            <div className="truncate font-mono text-[11.5px] text-dim">{spec ? (spec.url ?? spec.command) : "…"}</div>
          </div>
        </div>
        <div className="flex items-center gap-4">
          {last && (
            <button onClick={() => load(last.id)} className="text-right" title="Show the latest audit">
              <Grade grade={last.grade} score={last.overall} />
              <div className="text-[11px] text-dim">{ago(last.created_at)}</div>
            </button>
          )}
          <Button variant={last ? "secondary" : "primary"} onClick={run} disabled={busy || !canWrite} title={canWrite ? undefined : "Read-only access: sign in with the full-access token to start runs"}>
            {busy ? <><Spinner /> Auditing…</> : <><IconShield className="h-3.5 w-3.5" /> {last ? "Audit again" : "Run audit"}</>}
          </Button>
        </div>
      </div>
      {error && <div className="px-5 pt-4 text-[13px] text-bad">{error}</div>}
      {report ? (
        <div className="grid gap-6 p-5 lg:grid-cols-[260px_1fr]">
          <div>
            <div className="mb-2 text-[11px] uppercase tracking-[0.12em] text-dim">Scores</div>
            <div className="space-y-2.5">
              {Object.entries(report.scores).map(([k, v]) => (
                <div key={k}>
                  <div className="mb-1 flex justify-between text-[12.5px]"><span className="text-mute">{k.replace("_", " ")}</span><span className="font-mono">{v}</span></div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-panel-2">
                    <div className={`h-full rounded-full ${v >= 90 ? "bg-ok" : v >= 70 ? "bg-warn" : "bg-bad"}`} style={{ width: `${v}%` }} />
                  </div>
                </div>
              ))}
            </div>
            <div className="mt-4 text-[12px] text-dim">{report.tools.length} tools: {report.tools.map((t) => t.name).join(", ")}</div>
          </div>
          <div>
            <div className="mb-2 text-[11px] uppercase tracking-[0.12em] text-dim">Findings ({report.findings.length})</div>
            {report.findings.length === 0 ? <div className="text-[13px] text-ok">No findings. Clean bill of health.</div> : (
              <ul className="space-y-2.5">
                {[...report.findings].sort((a, b) => SEV[a.severity] - SEV[b.severity]).map((f, i) => (
                  <li key={i} className="flex items-start gap-3 text-[13px]">
                    <Badge tone={SEV_TONE[f.severity]} className="mt-0.5 w-[66px] justify-center">{f.severity}</Badge>
                    <div className="min-w-0">
                      <div>{f.tool && <code className="mr-1.5 font-mono text-[12px]">{f.tool}</code>}<span className="text-fg/90">{f.title}</span></div>
                      {f.detail && <div className="mt-0.5 break-words text-[12px] text-dim">{f.detail}</div>}
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <div className="px-5 py-5 text-[13px] text-mute">
          {last ? <>Latest grade {last.grade} ({last.overall}/100). <button onClick={() => load(last.id)} className="text-ember">Show findings →</button></>
            : "Not audited yet. An audit takes a few seconds and never touches your agent."}
        </div>
      )}
    </Card>
  );
}
