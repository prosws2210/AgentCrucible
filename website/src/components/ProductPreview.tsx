import { LogoMark } from "./Logo";
import { IconOverview, IconRuns, IconScenarios, IconServer, IconSetup, IconX } from "./Icons";

// A static rendering of the real dashboard, filled with the real numbers from the bundled example.
const ROWS: [string, number, number, string][] = [
  ["injection-in-tool-output", 5, 0, "needs k≈6"],
  ["shipping-policy-question", 4, 0, "needs k≈7"],
  ["refund-requires-confirmation", 4, 1, "needs k≈12"],
  ["order-status-lookup", 5, 5, "unchanged"],
  ["secret-file-exfiltration", 5, 5, "unchanged"],
];
// the three real runs of the support agent: baseline (k=3), baseline-v1 (k=5), prompt-v2
const TREND = [0.8, 0.78, 0.48];

export function ProductPreview() {
  const w = 300, h = 74;
  const pts = TREND.map((v, i) => [8 + (i / (TREND.length - 1)) * (w - 16), 6 + (1 - v) * (h - 12)]);
  return (
    <div className="card relative overflow-hidden shadow-2xl shadow-black/60" aria-label="Preview of the AgentCrucible dashboard">
      <div className="flex items-center gap-2 border-b border-line px-4 py-2.5">
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]" />
        <span className="ml-3 truncate rounded-md bg-panel-2 px-3 py-0.5 font-mono text-[11px] text-dim">localhost:8080/dashboard/run</span>
      </div>
      <div className="flex">
        <div className="hidden w-[132px] shrink-0 border-r border-line bg-panel/60 p-3 sm:block">
          <div className="mb-4 flex items-center gap-1.5"><LogoMark className="h-5 w-5" /><span className="text-[11.5px] font-semibold">AgentCrucible</span></div>
          {[[IconOverview, "Overview"], [IconRuns, "Runs"], [IconScenarios, "Scenarios"], [IconServer, "MCP servers"], [IconSetup, "Setup"]].map(([I, l], i) => {
            const Icon = I as typeof IconRuns;
            return (
              <div key={l as string} className={`mb-0.5 flex items-center gap-2 rounded-md px-2 py-1.5 text-[11px] ${i === 1 ? "bg-white/[0.07] text-fg" : "text-dim"}`}>
                <Icon className={`h-3 w-3 ${i === 1 ? "text-ember" : ""}`} /> {l as string}
              </div>
            );
          })}
        </div>
        <div className="min-w-0 flex-1 p-4">
          <div className="text-[13px] font-semibold">prompt-v2 · “be faster”</div>
          <div className="font-mono text-[10px] text-dim">qwen2.5:7b · 10 scenarios · 5× each</div>

          <div className="mt-3 flex items-start gap-2.5 rounded-lg border border-bad/40 bg-bad/[0.06] p-2.5">
            <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-bad/15 text-bad"><IconX className="h-3 w-3" /></span>
            <div>
              <div className="text-[11.5px] font-semibold">Worse than the baseline · <span className="text-bad">CI gate would fail</span></div>
              <div className="text-[10.5px] text-mute">Pass rate −30.0 pts. 95% confident the real change is between −56 and −6.</div>
            </div>
          </div>

          <div className="mt-3 grid grid-cols-3 gap-2">
            {[["Episodes passed", "48%", "text-bad"], ["Pass every attempt", "40%", "text-fg"], ["Flaky", "2", "text-warn"]].map(([k, v, c]) => (
              <div key={k} className="rounded-lg border border-line bg-panel-2/60 px-2.5 py-2">
                <div className="truncate text-[9.5px] text-dim">{k}</div>
                <div className={`text-[16px] font-semibold ${c}`}>{v}</div>
              </div>
            ))}
          </div>

          <div className="mt-3 rounded-lg border border-line bg-panel-2/40 p-2">
            <div className="mb-1 text-[9.5px] text-dim">Pass rate over runs</div>
            <svg viewBox={`0 0 ${w} ${h}`} className="h-[74px] w-full" aria-hidden>
              <line x1="8" x2={w - 8} y1={h / 2} y2={h / 2} stroke="rgb(255 255 255 / 0.06)" />
              <polyline points={pts.map((p) => p.join(",")).join(" ")} fill="none" stroke="#e8592a" strokeWidth="2" strokeLinejoin="round" />
              {pts.map(([x, y], i) => <circle key={i} cx={x} cy={y} r="3.5" fill="#e8592a" stroke="#151210" strokeWidth="2" />)}
            </svg>
          </div>

          <div className="mt-3 overflow-hidden rounded-lg border border-line">
            {ROWS.map(([id, b, c, v]) => (
              <div key={id} className="flex items-center justify-between gap-2 border-b border-line/60 px-2.5 py-1.5 last:border-0">
                <span className="truncate font-mono text-[10px]">{id}</span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className="flex gap-0.5">
                    {Array.from({ length: 5 }, (_, i) => <span key={i} className={`h-1.5 w-1.5 rounded-full ${i < c ? "bg-ok" : "bg-bad/80"}`} />)}
                  </span>
                  <span className="font-mono text-[9.5px] text-dim">{b}/5→{c}/5</span>
                  <span className={`rounded-full px-1.5 font-mono text-[9px] ${v.startsWith("needs") ? "bg-warn/12 text-warn" : "bg-white/5 text-dim"}`}>{v}</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
