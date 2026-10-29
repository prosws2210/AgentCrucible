"use client";

import { useState } from "react";
import { PageHeader, SOURCE, useProject } from "@/components/app/AppShell";
import { IconPlus } from "@/components/Icons";
import { Badge, Button, PassRate } from "@/components/ui";
import { api, type ProjectSummary } from "@/lib/api";
import { ago } from "@/lib/format";

export default function ProjectsPage() {
  const { projects, project } = useProject();
  return (
    <>
      <PageHeader
        title="Projects"
        sub="A project is one codebase's tests: one crucible.yaml with any number of agents. Imports and agents you add in another codebase become projects here. Pick one to work on; the sidebar shows which is open."
        actions={<Button href="/dashboard/add/"><IconPlus /> Add agents or a codebase</Button>}
      />
      <div className="grid gap-4 md:grid-cols-2">
        {projects.map((p) => <ProjectCard key={p.id} p={p} current={p.id === project.id} />)}
      </div>
    </>
  );
}

function ProjectCard({ p, current }: { p: ProjectSummary; current: boolean }) {
  const { switchProject, refresh, canWrite } = useProject();
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function remove() {
    try {
      await api(`/api/projects/${p.id}`, { method: "DELETE" });
      if (current) switchProject("home");
      else refresh();
    } catch (e) {
      setError((e as Error).message);
    }
  }
  return (
    <div className={`card flex flex-col p-5 ${current ? "border-ember/50" : ""}`}>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[16px] font-semibold">{p.name}</div>
          <div className="truncate font-mono text-[11.5px] text-dim" title={p.path}>{p.codebase ?? p.root}</div>
        </div>
        <div className="flex shrink-0 gap-1.5">
          {current && <Badge tone="ember">open</Badge>}
          <Badge>{SOURCE[p.source] ?? p.source}</Badge>
        </div>
      </div>
      {p.error ? (
        <p className="mt-3 break-words text-[12.5px] text-bad">{p.error}</p>
      ) : (
        <>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {p.agents.map((a) => <span key={a} className="rounded-md bg-white/5 px-2 py-0.5 font-mono text-[11.5px] text-mute">{a}</span>)}
          </div>
          <div className="mt-4 flex flex-wrap items-center gap-x-5 gap-y-2 text-[12.5px] text-mute">
            <span><b className="text-fg">{p.agents.length}</b> agent{p.agents.length === 1 ? "" : "s"}</span>
            <span><b className="text-fg">{p.scenarios}</b> scenarios</span>
            {p.last_run ? (
              <span className="flex items-center gap-2">last run {ago(p.last_run.created_at)} <PassRate value={p.last_run.pass_at_1} /></span>
            ) : <span>no runs yet</span>}
          </div>
        </>
      )}
      {error && <p className="mt-2 text-[12.5px] text-bad">{error}</p>}
      <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-5">
        {!p.home && canWrite ? (
          confirm ? (
            <span className="flex items-center gap-2 text-[12.5px]">
              <span className="text-mute">Remove from the dashboard? Files stay.</span>
              <Button variant="ghost" onClick={remove} className="!text-bad">Remove</Button>
              <Button variant="ghost" onClick={() => setConfirm(false)}>Keep</Button>
            </span>
          ) : <Button variant="ghost" onClick={() => setConfirm(true)}>Remove</Button>
        ) : <span />}
        {!current && !p.error && <Button variant="secondary" onClick={() => switchProject(p.id, "/dashboard/")}>Open project</Button>}
      </div>
    </div>
  );
}
