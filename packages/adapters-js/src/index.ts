// AgentCrucible adapters for TypeScript and JavaScript agents.
//
// A generated adapter (written by `crucible discover --apply`) is a few lines:
//
//   import { serveAgent, instrumentModule } from "./crucible";
//   import * as mod from "../../src/agent";
//   instrumentModule(mod);                       // trace (and mock / block) the tools it exports
//   serveAgent(mod.supportAgent, "mastra");      // one JSON line per turn over stdin/stdout
//
// `serve` speaks AgentCrucible's stdio protocol. Tool wrappers report each call and result to the episode's gateway
// (CRUCIBLE_EVENTS_URL) and apply the scenario's mocks (CRUCIBLE_TOOL_MOCKS, including document snapshots for RAG),
// blocked tools (CRUCIBLE_DENY_TOOLS) and injected text (CRUCIBLE_TOOL_INJECT), like the Python adapters.
// No dependencies; Node 18+.

import { readFileSync, statSync } from "node:fs";
import * as readline from "node:readline";

export type Msg = { role: "user" | "assistant"; content: string };
export type Turn = (history: Msg[]) => Promise<string> | string;
type AnyFn = (...args: any[]) => any;

// ---------------------------------------------------------------- protocol

/** Run the stdio protocol: read `{"type":"user","content":…}` lines, answer `{"type":"assistant","content":…}`. */
export async function serve(turn: Turn): Promise<void> {
  const out = console.log.bind(console);
  console.log = (...a: unknown[]) => console.error(...a); // stray logging must not corrupt the protocol
  const history: Msg[] = [];
  const rl = readline.createInterface({ input: process.stdin });
  for await (const line of rl) {
    let msg: { type?: string; content?: unknown };
    try {
      msg = JSON.parse(line);
    } catch {
      continue;
    }
    if (msg.type === "end") break;
    if (msg.type !== "user") continue;
    history.push({ role: "user", content: String(msg.content ?? "") });
    let reply: string;
    try {
      reply = asText(await turn([...history]));
    } catch (e) {
      console.error(e);
      reply = `[agent error] ${e instanceof Error ? `${e.name}: ${e.message}` : String(e)}`;
    }
    history.push({ role: "assistant", content: reply });
    out(JSON.stringify({ type: "assistant", content: reply }));
  }
  rl.close();
}

/** Pull the answer out of whatever the agent returned. */
export function asText(r: unknown): string {
  if (r == null) return "";
  if (typeof r === "string") return r;
  if (typeof r !== "object") return String(r);
  const o = r as Record<string, unknown>;
  for (const k of ["text", "finalOutput", "output", "content", "response", "answer", "reply", "result"]) {
    if (typeof o[k] === "string") return o[k] as string;
  }
  if (Array.isArray(o.messages) && o.messages.length) return asText(o.messages[o.messages.length - 1]);
  if (Array.isArray(r) && r.length) return asText(r[r.length - 1]);
  return JSON.stringify(r);
}

// ---------------------------------------------------------------- frameworks

/** One turn for an agent object or function, by framework. */
export function turnFor(agent: any, framework = "generic"): Turn {
  if (framework === "mastra" || typeof agent?.generate === "function") {
    return async (h) => asText(await agent.generate(h.map((m) => ({ role: m.role, content: m.content }))));
  }
  if (framework === "openai-agents-js") {
    return async (h) => {
      const { run } = await import("@openai/agents" as string);
      const r = await run(agent, h.map((m) => ({ role: m.role, content: m.content })));
      return String(r.finalOutput ?? "");
    };
  }
  if (framework === "langgraph-js" || typeof agent?.invoke === "function") {
    return async (h) => asText(await agent.invoke({ messages: h.map((m) => ({ role: m.role, content: m.content })) }));
  }
  if (typeof agent === "function") {
    // a function that answers one message (gets the history too): Vercel AI SDK and plain code
    return async (h) => asText(await agent(h[h.length - 1].content, h));
  }
  throw new Error(`don't know how to call ${typeof agent} for framework ${framework}`);
}

export function serveAgent(agent: any, framework = "generic"): Promise<void> {
  instrumentAgent(agent);
  return serve(turnFor(agent, framework));
}

// ---------------------------------------------------------------- tools

function env<T>(name: string, fallback: T): T {
  try {
    return process.env[name] ? (JSON.parse(process.env[name] as string) as T) : fallback;
  } catch {
    return fallback;
  }
}

/** Report tool events to the episode's gateway (no-op outside a test run). */
export async function emit(...events: Record<string, unknown>[]): Promise<void> {
  const url = process.env.CRUCIBLE_EVENTS_URL;
  if (!url) return;
  try {
    await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(events) });
  } catch (e) {
    console.error(`[agentcrucible] tracing failed: ${e}`);
  }
}

const short = (v: unknown, n = 4000) => (typeof v === "string" ? v : JSON.stringify(v) ?? String(v)).slice(0, n);

/** Wrap one tool function: trace it, and apply the scenario's mock / block / inject for `name`. */
export function traceTool<F extends AnyFn>(name: string, fn: F): F {
  if ((fn as any).__crucibleTraced) return fn;
  const wrapped = async function (this: unknown, ...args: any[]) {
    const input = args.length === 1 ? args[0] : args;
    const call: Record<string, unknown> = { type: "tool_call", tool: name, args: typeof input === "object" && input !== null ? input : { input } };
    const deny = env<string[]>("CRUCIBLE_DENY_TOOLS", []);
    const mocks = env<Record<string, unknown>>("CRUCIBLE_TOOL_MOCKS", {});
    if (deny.includes(name)) {
      const text = `Tool '${name}' is blocked by test policy.`;
      await emit({ ...call, blocked: true }, { type: "tool_result", tool: name, content: text, is_error: true });
      return text;
    }
    if (name in mocks) {
      let mock = mocks[name];
      if (isSnapshotMock(mock)) mock = snapshotAnswer(mock, input);
      await emit({ ...call, mocked: true }, { type: "tool_result", tool: name, content: short(mock) });
      return mock;
    }
    await emit(call);
    const start = Date.now();
    try {
      let result = await fn.apply(this, args);
      const inject = env<Record<string, string>>("CRUCIBLE_TOOL_INJECT", {})[name];
      if (inject) result = `${typeof result === "string" ? result : JSON.stringify(result)}\n\n${inject}`;
      await emit({ type: "tool_result", tool: name, content: short(result), duration_ms: Date.now() - start });
      return result;
    } catch (e) {
      await emit({ type: "tool_result", tool: name, content: String(e), is_error: true, duration_ms: Date.now() - start });
      throw e;
    }
  };
  (wrapped as any).__crucibleTraced = true;
  return wrapped as unknown as F;
}

const isTool = (v: any) => v && typeof v === "object" && typeof v.execute === "function";

/** Wrap every tool in a tool set: `{ name: tool({ execute }) }` (Vercel AI SDK) or Mastra `createTool` objects. */
export function instrumentTools<T extends Record<string, any>>(tools: T): T {
  for (const [key, t] of Object.entries(tools ?? {})) {
    if (isTool(t)) t.execute = traceTool(t.id ?? key, t.execute);
  }
  return tools;
}

/** Wrap the tools an agent object holds (Mastra `Agent`, OpenAI Agents `Agent`). */
export function instrumentAgent(agent: any): void {
  if (!agent || typeof agent !== "object") return;
  for (const holder of [agent.tools, agent.__tools, agent._tools, agent.options?.tools]) {
    if (holder && typeof holder === "object" && !Array.isArray(holder)) instrumentTools(holder);
    if (Array.isArray(holder)) holder.forEach((t: any) => isTool(t) && (t.execute = traceTool(t.name ?? t.id, t.execute)));
  }
}

/** Wrap every tool set and agent a module exports. */
export function instrumentModule(mod: Record<string, any>): void {
  for (const v of Object.values(mod ?? {})) {
    if (!v || typeof v !== "object") continue;
    if (isTool(v)) v.execute = traceTool(v.id ?? v.name ?? "tool", v.execute);
    else if (Object.values(v).some(isTool)) instrumentTools(v);
    else instrumentAgent(v);
  }
}

// ---------------------------------------------------------------- RAG snapshots (same index as agentcrucible.snapshot)

const STOP = new Set(("a an and are as at be but by can do does for from has have how i if in into is it its me my no not of on " +
  "or our please so than that the their them then there these they this to was we what when where which who why will " +
  "with you your about any some tell know find check give get").split(" "));
const words = (t: string) => (t.toLowerCase().match(/[a-z0-9][a-z0-9-]{1,}/g) ?? []).filter((w) => !STOP.has(w));
const QUERY_KEYS = ["query", "question", "q", "input", "text", "search", "search_query", "prompt", "message", "topic"];
type Passage = { source: string; text: string };
const loaded = new Map<string, { mtime: number; passages: Passage[]; tfs: Map<string, number>[]; idf: Map<string, number>; avg: number }>();

function isSnapshotMock(m: unknown): m is { snapshot: string; k?: number } {
  return !!m && typeof m === "object" && typeof (m as any).snapshot === "string";
}

export function searchSnapshot(path: string, query: string, k = 3): Passage[] {
  const mtime = statSync(path).mtimeMs;
  let idx = loaded.get(path);
  if (!idx || idx.mtime !== mtime) {
    const passages: Passage[] = JSON.parse(readFileSync(path, "utf8")).passages ?? [];
    const tfs = passages.map((p) => {
      const tf = new Map<string, number>();
      for (const w of words(`${p.source} ${p.text}`)) tf.set(w, (tf.get(w) ?? 0) + 1);
      return tf;
    });
    const n = Math.max(passages.length, 1);
    const df = new Map<string, number>();
    tfs.forEach((tf) => tf.forEach((_, w) => df.set(w, (df.get(w) ?? 0) + 1)));
    const idf = new Map([...df].map(([w, c]) => [w, Math.log(1 + (n - c + 0.5) / (c + 0.5))]));
    const avg = tfs.reduce((s, tf) => s + [...tf.values()].reduce((a, b) => a + b, 0), 0) / n || 1;
    idx = { mtime, passages, tfs, idf, avg };
    loaded.set(path, idx);
  }
  const q = new Set(words(query));
  const scored: [number, number][] = [];
  idx.tfs.forEach((tf, i) => {
    const len = [...tf.values()].reduce((a, b) => a + b, 0);
    let s = 0;
    for (const w of q) {
      const f = tf.get(w);
      if (f) s += (idx!.idf.get(w) ?? 0) * f * 2.2 / (f + 1.2 * (0.25 + 0.75 * len / idx!.avg));
    }
    if (s > 0) scored.push([s, i]);
  });
  return scored.sort((a, b) => b[0] - a[0]).slice(0, k).map(([, i]) => idx!.passages[i]);
}

function queryOf(input: unknown): string {
  if (typeof input === "string") return input;
  if (input && typeof input === "object") {
    const o = input as Record<string, unknown>;
    for (const k of QUERY_KEYS) if (typeof o[k] === "string") return o[k] as string;
    const strings = Object.values(o).filter((v): v is string => typeof v === "string");
    if (strings.length) return strings.sort((a, b) => b.length - a.length)[0];
  }
  return "";
}

function snapshotAnswer(mock: { snapshot: string; k?: number }, input: unknown): string {
  const hits = searchSnapshot(mock.snapshot, queryOf(input), mock.k ?? 3);
  return hits.length ? hits.map((h) => `[${h.source}]\n${h.text}`).join("\n\n") : "No results.";
}
