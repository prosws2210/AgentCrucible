import type { Check, TrajectoryEvent } from "@/lib/api";

/** Tools named in failed checks (forbidden calls, premature calls) are highlighted in the timeline. */
export function flaggedTools(checks: Check[]): Set<string> {
  const out = new Set<string>();
  for (const c of checks) {
    if (c.passed) continue;
    const m = c.detail.match(/called forbidden: \[(.*?)\]/);
    if (m) m[1].split(",").forEach((t) => out.add(t.replace(/['"\s]/g, "")));
    const early = c.detail.match(/^(\w+) called in turn/);
    if (early) out.add(early[1]);
  }
  return out;
}

export function TrajectoryTimeline({ events, flagged = new Set() }: { events: TrajectoryEvent[]; flagged?: Set<string> }) {
  const shown = events.filter((e) => e.type !== "episode_start" && e.type !== "episode_end");
  if (!shown.length) return <div className="px-5 py-8 text-center text-[13px] text-dim">No events recorded.</div>;
  return (
    <ol className="px-4 py-2 sm:px-5">
      {shown.map((e, i) => (
        <Event key={i} e={e} bad={e.type === "tool_call" && flagged.has(e.tool ?? "")} />
      ))}
    </ol>
  );
}

function Event({ e, bad }: { e: TrajectoryEvent; bad: boolean }) {
  const row = (icon: string, body: React.ReactNode, extra = "") => (
    <li className={`flex gap-3 border-b border-line/60 py-3 last:border-0 ${extra}`}>
      <span className="w-11 shrink-0 pt-0.5 font-mono text-[11px] text-dim">{e.t.toFixed(1)}s</span>
      <span className="w-5 shrink-0 text-center text-[13px]" aria-hidden>{icon}</span>
      <div className="min-w-0 flex-1 text-[13px]">{body}</div>
    </li>
  );

  switch (e.type) {
    case "user_message":
      return row("👤", <Bubble who={`User${e.turn ? ` · turn ${e.turn}` : ""}`} text={e.content ?? ""} />);
    case "assistant_message":
      return row("🤖", <Bubble who="Agent" text={e.content ?? ""} />);
    case "llm_call":
      return row(
        "🧠",
        e.error ? (
          <span className="text-bad">LLM call failed: {e.error}</span>
        ) : (
          <span className="text-mute">
            LLM <code className="font-mono text-[12px] text-fg">{e.model}</code>
            {e.api && <Tag tone="mute">{e.api}{e.stream ? " · stream" : ""}{e.cache && e.cache !== "off" ? ` · ${e.cache}` : ""}</Tag>}{" "}
            {e.tokens_in}→{e.tokens_out} tok · {Math.round(e.latency_ms ?? 0)} ms
            {e.tool_calls?.length ? (
              <>
                {" "}· wants <span className="text-amber">{e.tool_calls.join(", ")}</span>
              </>
            ) : null}
          </span>
        ),
      );
    case "tool_call":
      return row(
        "🔧",
        <>
          <div className="flex flex-wrap items-center gap-1.5">
            <code className={`font-mono text-[12.5px] font-semibold ${bad ? "text-bad" : "text-fg"}`}>
              {e.server}.{e.tool}
            </code>
            {bad && <Tag tone="bad">flagged by a check</Tag>}
            {e.blocked && <Tag tone="bad">blocked</Tag>}
            {e.mocked && <Tag tone="mute">mocked</Tag>}
            {e.injected && <Tag tone="warn">attack injected into result</Tag>}
          </div>
          <pre className="code mt-1.5 max-h-56 overflow-auto rounded-lg bg-panel-2 px-3 py-2 text-[12px] text-mute">
            {JSON.stringify(e.args ?? {}, null, 1)}
          </pre>
        </>,
        bad ? "-mx-4 bg-bad/[0.07] px-4 sm:-mx-5 sm:px-5" : "",
      );
    case "tool_result": {
      const text = (e.content ?? "").trim();
      const attack = /SYSTEM OVERRIDE|NOTE TO AI AGENTS|Ignore (all )?previous instructions/i.test(text);
      return row(
        "↩",
        <>
          <span className="text-mute">
            result {e.is_error && <span className="text-bad">· error</span>} <span className="text-dim">· {e.latency_ms} ms</span>
          </span>
          <pre
            className={`code mt-1.5 max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-lg px-3 py-2 text-[12px] ${
              attack ? "border border-warn/30 bg-warn/[0.06] text-warn" : "bg-panel-2 text-mute"
            }`}
          >
            {text || "(empty)"}
          </pre>
        </>,
      );
    }
    case "error":
      return row("⚠", <span className="text-bad">{e.message}</span>, "-mx-4 bg-bad/[0.07] px-4 sm:-mx-5 sm:px-5");
    default:
      return row("·", <span className="text-dim">{e.type.replace(/_/g, " ")}</span>);
  }
}

function Bubble({ who, text }: { who: string; text: string }) {
  return (
    <>
      <div className="mb-1 text-[12px] font-medium text-mute">{who}</div>
      <p className="whitespace-pre-wrap break-words leading-relaxed text-fg/90">{text}</p>
    </>
  );
}

function Tag({ tone, children }: { tone: "bad" | "warn" | "mute"; children: React.ReactNode }) {
  const cls = tone === "bad" ? "border-bad/40 text-bad" : tone === "warn" ? "border-warn/40 text-warn" : "border-line text-dim";
  return <span className={`ml-1.5 rounded border px-1.5 py-px font-mono text-[10.5px] ${cls}`}>{children}</span>;
}
