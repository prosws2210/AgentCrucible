"use client";

import { PageHeader, useProject } from "@/components/app/AppShell";
import { AgentCard, useAgents } from "@/components/app/agents";
import { IconAgents, IconPlus } from "@/components/Icons";
import { Button, Card, Empty, Spinner } from "@/components/ui";

export default function AgentsPage() {
  const { project } = useProject();
  const agents = useAgents();
  const list = agents.data ?? [];
  const failing = list.filter((a) => a.failing > 0).length;
  const untested = list.filter((a) => a.scenarios > 0 && !a.tested).length;
  return (
    <>
      <PageHeader
        title="Agents"
        sub={<>Every agent in <b className="text-fg">{project.project}</b>, how it&apos;s connected, and how its tests did last time. Run one agent&apos;s tests on its own, or everything from Runs.</>}
        actions={<Button href="/dashboard/add/"><IconPlus /> Add agents</Button>}
      />
      {agents.error && <Card className="mb-4 p-5 text-[13px] text-bad">{agents.error}</Card>}
      {!agents.data ? (
        <div className="flex items-center justify-center gap-2 py-24 text-[13px] text-dim"><Spinner /> Loading agents…</div>
      ) : list.length === 0 ? (
        <Card>
          <Empty icon={<IconAgents />} title="No agents yet" action={<Button href="/dashboard/add/"><IconPlus /> Add agents</Button>}>
            Import a codebase to find every agent in it, or add one by hand.
          </Empty>
        </Card>
      ) : (
        <>
          {list.length > 1 && (
            <p className="mb-4 text-[13px] text-mute">
              {list.length} agents{failing ? <> · <span className="text-bad">{failing} with failing tests</span></> : null}
              {untested ? <> · {untested} not run yet</> : null}
            </p>
          )}
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {list.map((a) => <AgentCard key={a.name} a={a} />)}
          </div>
        </>
      )}
    </>
  );
}
