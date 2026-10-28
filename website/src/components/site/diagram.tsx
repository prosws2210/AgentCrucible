import { LogoMark } from "../Logo";
import { Code } from "../ui";

/** Connect → Describe → Gate, shown on the home page and at the top of "How it works". */
export function ThreeSteps() {
  return (
    <div className="grid gap-5 lg:grid-cols-3">
      <Step n={1} title="Connect" body="Point your agent's model URL and MCP server URLs at AgentCrucible. The OpenAI and Anthropic SDKs read them from the environment already.">
        <Code copy={false} small title="what your agent receives" code={`OPENAI_BASE_URL=…/v1\nCRUCIBLE_MCP_SHOP_URL=…/mcp/shop`} />
      </Step>
      <Step n={2} title="Describe" body="Write scenarios as YAML: what the user says, and what must and must never happen. Each runs in a fresh sandbox.">
        <Code copy={false} small title="scenarios/refund.yaml" code={`task: Refund my mouse, please.\nchecks:\n  - state.sql: { … expect: 1 }\n  - trajectory.not_before_turn:\n      tool: issue_refund\n      turn: 2`} />
      </Step>
      <Step n={3} title="Gate" body="Every change gets a verdict: better, worse, or not sure yet. On pull requests it comments and passes or fails the check.">
        <div className="rounded-xl border border-line bg-panel-2/60 p-4 text-[12.5px]">
          <div className="flex items-center gap-2 text-mute"><LogoMark className="h-4 w-4" /> crucible-bot</div>
          <div className="mt-2 font-medium text-bad">✕ Worse than baseline: −30.0 pts</div>
          <div className="mt-1 text-mute">injection-in-tool-output 5/5 → 0/5</div>
          <div className="text-mute">refund-requires-confirmation 4/5 → 1/5</div>
        </div>
      </Step>
    </div>
  );
}

function Step({ n, title, body, children }: { n: number; title: string; body: string; children: React.ReactNode }) {
  return (
    <div className="card flex flex-col p-6">
      <div className="flex items-center gap-3">
        <span className="flex h-8 w-8 items-center justify-center rounded-full bg-ember/15 font-mono text-[13px] text-ember">{n}</span>
        <h3 className="text-[19px] font-semibold tracking-tight">{title}</h3>
      </div>
      <p className="mb-5 mt-3 text-[14.5px] leading-relaxed text-mute">{body}</p>
      <div className="mt-auto">{children}</div>
    </div>
  );
}

/** One episode: who talks to whom, and where AgentCrucible sits. */
export function EpisodeDiagram() {
  return (
    <div className="card p-5 sm:p-7">
      <div className="mb-5 font-mono text-[11.5px] uppercase tracking-[0.14em] text-dim">What happens in each test, called an episode</div>
      <div className="grid items-stretch gap-3 lg:grid-cols-[1fr_auto_1.1fr_auto_1fr_auto_1fr]">
        <Box title="Simulated user" sub="Plays the customer from a persona" />
        <Arrow />
        <Box title="Your agent" sub="Unchanged, any framework" accent />
        <Arrow />
        <Box title="Model gateway" sub="Records every call; can force a model" accent />
        <Arrow />
        <Box title="Your model" sub="Ollama, OpenAI, Anthropic, vLLM…" />
      </div>
      <div className="mt-3 grid items-stretch gap-3 lg:grid-cols-[1fr_auto_1.1fr_auto_1fr_auto_1fr]">
        <div className="hidden lg:block" />
        <div className="hidden lg:block" />
        <div className="flex items-center justify-center text-[12px] text-dim lg:justify-end">tool calls go through ↘</div>
        <div className="hidden lg:block" />
        <Box title="Tool gateway" sub="Records, mocks, blocks, injects attacks" accent />
        <Arrow />
        <Box title="Your MCP servers" sub="Fresh process + clean database or repo, or your remote server" />
      </div>
      <div className="mt-6 flex flex-wrap items-center gap-x-6 gap-y-2 border-t border-line pt-5 text-[13.5px] text-mute">
        <span className="font-medium text-fg">Then:</span>
        {["grade the outcome", "repeat several times", "compare with the baseline", "pass or fail the gate"].map((x, i) => (
          <span key={x} className="flex items-center gap-2"><span className="font-mono text-[11px] text-ember">{i + 1}</span>{x}</span>
        ))}
      </div>
    </div>
  );
}

function Box({ title, sub, accent }: { title: string; sub: string; accent?: boolean }) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${accent ? "border-ember/50 bg-ember/[0.07]" : "border-line bg-panel-2"}`}>
      <div className="text-[14px] font-semibold">{title}</div>
      <div className="mt-0.5 text-[12.5px] leading-snug text-mute">{sub}</div>
    </div>
  );
}

function Arrow() {
  return (
    <div className="flex items-center justify-center px-1 text-dim">
      <span className="text-lg leading-none lg:hidden">↓</span>
      <span className="hidden text-lg leading-none lg:inline">→</span>
    </div>
  );
}
