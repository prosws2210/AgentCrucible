"use client";

import { useState } from "react";
import { PageHeader, useProject } from "@/components/app/AppShell";
import { useGraphLinks } from "@/components/app/graph";
import { IconExternal, IconRefresh } from "@/components/Icons";
import { Button, Code } from "@/components/ui";
import { API } from "@/lib/api";

export default function GraphPage() {
  const { project } = useProject();
  const [version, setVersion] = useState(0);
  useGraphLinks();
  const src = `${API}/api/graph.html?project=${encodeURIComponent(project.id)}${version ? `&refresh=1&v=${version}` : ""}`;
  const file = `${project.root.replace(/[\\/]$/, "")}/knowledge-graph.html`;
  return (
    <>
      <PageHeader
        title="Knowledge graph"
        sub={<>Every file in <b className="text-fg">{project.project}</b> that holds an agent, a tool or an MCP server, how they import each other, and what each agent uses. Click an agent or MCP server to light up everywhere it&apos;s used.</>}
        actions={<>
          <Button variant="secondary" onClick={() => setVersion((v) => v + 1)}><IconRefresh className="h-3.5 w-3.5" /> Rebuild</Button>
          <Button variant="ghost" href={src} external>Open full screen <IconExternal className="h-3.5 w-3.5" /></Button>
        </>}
      />
      <div className="card overflow-hidden">
        <iframe key={src} src={src} title={`Knowledge graph of ${project.project}`} className="block h-[72vh] min-h-[460px] w-full border-0 bg-ink" />
      </div>
      <div className="mt-5 grid gap-4 lg:grid-cols-2">
        <div className="card p-5 text-[13px] text-mute">
          <div className="mb-1 text-[14px] font-semibold text-fg">It&apos;s in your repository too</div>
          Every import writes <code className="font-mono text-[12px]">knowledge-graph.json</code> and a viewer,{" "}
          <code className="break-all font-mono text-[12px] text-fg">{file}</code>, next to the tests. Open the HTML file in any
          browser: it needs no server or network. Commit it with the tests to keep it with the code.
        </div>
        <div className="card p-5">
          <div className="mb-2 text-[14px] font-semibold">Rebuild it from the terminal</div>
          <Code title="terminal" code={`crucible graph .            # from agent-tests/discovery.json\ncrucible graph . --rescan   # read the code again`} />
        </div>
      </div>
    </>
  );
}
