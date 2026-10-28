// FAQ content, shared by the FAQ page and the short FAQ on the home page.
import Link from "next/link";

export const FAQ_GROUPS: [string, [string, React.ReactNode][]][] = [
  ["Getting started", [
    ["Do I have to change my agent?", <>No logic changes. Your agent reads its model URL and MCP server URLs from the environment (most SDKs already do), and either talks over stdin/stdout or exposes one HTTP endpoint. The <Link href="/start/" className="text-ember">setup wizard</Link> writes the small adapter for you.</>],
    ["Which frameworks and models work?", "Anything that calls an OpenAI-compatible API (Chat Completions or the Responses API) or the Anthropic Messages API: the OpenAI and Anthropic SDKs, LangGraph, CrewAI, AutoGen, Vercel AI SDK or plain code. Models can be local (Ollama, vLLM) or hosted (OpenAI, Anthropic, OpenRouter)."],
    ["How long does setup take?", "About five minutes for the config and a first scenario with the wizard. Writing 10–20 good scenarios from real support tickets or incidents is the part worth a day."],
    ["Can it test an agent that's already deployed?", "Yes. Point the HTTP transport at your staging URL (with an auth header if needed) and AgentCrucible sends each test there with the gateway addresses in the request."],
  ]],
  ["Data, security and cost", [
    ["Does my data leave my machine?", "No. AgentCrucible is self-hosted: the CLI, the dashboard and the database run where you run them. The only outside calls are the ones your agent already makes to your model provider."],
    ["What does it cost?", "The software is free and open source (Apache-2.0). Running tests costs whatever your model provider charges; with local models it is free, and recorded responses can be replayed at no cost."],
    ["Can I share the dashboard with my team?", "Yes. Set CRUCIBLE_API_TOKEN (full access) and optionally CRUCIBLE_VIEWER_TOKEN (read-only) and the dashboard asks for a token. For per-person accounts, put your SSO proxy in front of it."],
    ["Is it safe to run an untrusted agent?", "Agents and MCP servers run as child processes with a fresh temp directory per episode. For untrusted code use the container or the Kubernetes setup (non-root, read-only filesystem, egress limited by a NetworkPolicy)."],
  ]],
  ["Results and statistics", [
    ["How many runs do I need?", "3 attempts per scenario to explore, 5 or more for a baseline you gate on. When the evidence is too thin to call a change, the report says so and estimates how many attempts would settle it."],
    ["Why not just run each test once?", "Because agents are random. In our example, single-attempt testing said the agent worked 78% of the time; only 50% of scenarios passed all five attempts."],
    ["What does “inconclusive” mean?", "The scenario got worse or better, but not by enough to rule out chance with the attempts you ran. The verdict comes with a “needs k≈N” estimate."],
    ["Can I trust an LLM judge?", "Only as far as it agrees with you. Label some episodes, run crucible calibrate, and the judge's checks are demoted to non-blocking if agreement (Cohen's κ) is below 0.6."],
  ]],
  ["CI and MCP servers", [
    ["How does it work in CI?", <>Add the GitHub Action to your workflow. It runs the suite, compares with the latest run on your main branch, comments on the pull request and fails the check on a significant regression. See the <Link href="/docs/#ci" className="text-ember">CI docs</Link>.</>],
    ["What about MCP servers I build?", "Run an audit on them: protocol conformance, tool-description quality, fuzzing, security probes and latency, in a few seconds, with a graded report card. Local commands and remote URLs both work."],
    ["Can my agent use a remote MCP server?", "Yes: declare it with url (Streamable HTTP or SSE) and headers. Remember that its state is shared across attempts, so prefer staging or mocks for tools with side effects."],
  ]],
];

/** One question, by its exact text (throws at build time if it was renamed). */
export function faq(q: string): [string, React.ReactNode] {
  for (const [, qs] of FAQ_GROUPS) for (const item of qs) if (item[0] === q) return item;
  throw new Error(`no FAQ entry: ${q}`);
}

export function FaqItem({ q, a }: { q: string; a: React.ReactNode }) {
  return (
    <details className="card group px-5 py-4 [&_summary::-webkit-details-marker]:hidden">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-4 text-[15.5px] font-medium">
        {q}
        <span className="text-xl leading-none text-dim transition-transform group-open:rotate-45">+</span>
      </summary>
      <div className="mt-3 text-[14.5px] leading-relaxed text-mute">{a}</div>
    </details>
  );
}
