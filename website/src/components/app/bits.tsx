import { IconCheck, IconX } from "../Icons";
import { Badge, Spinner } from "../ui";
import type { Run } from "@/lib/api";

export function Grade({ grade, score }: { grade: string; score: number }) {
  const c = grade === "A" || grade === "B" ? "text-ok" : grade === "C" ? "text-warn" : "text-bad";
  return (
    <span className="flex items-baseline gap-1.5">
      <span className={`font-serif text-[26px] leading-none ${c}`}>{grade}</span>
      <span className="font-mono text-[11px] text-dim">{score}</span>
    </span>
  );
}

export function RunStatus({ r }: { r: Run }) {
  if (r.status === "running" || r.status === "queued")
    return <Badge tone="info"><Spinner className="h-2.5 w-2.5" /> {r.progress ? `${r.progress.done}/${r.progress.total}` : r.status}</Badge>;
  if (r.status === "failed") return <Badge tone="bad">error</Badge>;
  if (r.status === "cancelled") return <Badge tone="warn">cancelled</Badge>;
  if (r.status === "interrupted") return <Badge tone="bad">interrupted</Badge>;
  if (r.gate === "fail") return <Badge tone="bad"><IconX className="h-3 w-3" /> gate failed</Badge>;
  if (!r.compare_to) {
    // no baseline: there is no better/worse verdict, so report the plain outcome
    return r.pass_at_1 === 1 ? <Badge tone="ok"><IconCheck className="h-3 w-3" /> all passed</Badge>
      : <Badge tone="warn">some failing</Badge>;
  }
  if (r.verdict === "improved") return <Badge tone="ok">improved</Badge>;
  return <Badge tone="ok"><IconCheck className="h-3 w-3" /> passed gate</Badge>;
}

