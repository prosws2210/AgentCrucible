// Typed client for the AgentCrucible backend (`crucible serve`).
// Same origin behind nginx (/api → backend). For `npm run dev`, set NEXT_PUBLIC_API_BASE=http://localhost:8000
export const API = process.env.NEXT_PUBLIC_API_BASE ?? "";

export type RunStatus = "queued" | "running" | "done" | "failed";

export type Run = {
  id: string;
  label: string;
  suite: string | null;
  model: string;
  status: RunStatus;
  created_at: string;
  finished_at: string | null;
  k: number | null;
  n_episodes: number | null;
  pass_at_1: number | null;
  pass_pow_k: number | null;
  compare_to: string | null;
  verdict: string | null;
  gate: string | null;
  error: string | null;
  params?: { agent_env?: Record<string, string>; scenarios?: string[] | null };
  progress?: { done: number; total: number; failed: number };
};

export type Health = { ok: boolean; db: string; llm_url: string; busy: boolean };

export type Role = "admin" | "viewer";
export type AuthStatus = { required: boolean; authenticated: boolean; role: Role | null };

export type Project = {
  project: string;
  model: string;
  suites: Record<string, { runs: number; scenarios: { id: string; description: string; tags: string[] }[] }>;
  mcp_servers: string[];
  prompt_presets: string[];
  fixtures: string[];
};

export type Config = {
  project: string;
  agent: { transport: "stdio" | "http"; command: string | null; url: string | null; turn_timeout_s: number };
  model: string;
  llm: { openai_base_url: string; anthropic_base_url: string; cache: string };
  mcp_servers: { name: string; command: string | null; url: string | null; remote: boolean }[];
  suites: Record<string, { path: string; runs: number }>;
  simulator_model: string;
  judge_model: string;
  gate: { fail_on: string[]; alpha: number };
};

export type DoctorCheck = { id: string; label: string; ok: boolean; detail: string };
export type Doctor = { ok: boolean; checks: DoctorCheck[] };

export type Scenario = {
  id: string;
  suite: string;
  description: string;
  tags: string[];
  runs: number;
  multi_turn: boolean;
  environment: string[];
  checks: { label: string; hard: boolean }[];
  task: string;
  latest: { run_id: string; run_label: string; passed: number; n: number } | null;
};

export type Check = { label: string; hard: boolean; passed: boolean; detail: string; score: number | null };
export type Totals = { llm_calls: number; tokens_in: number; tokens_out: number; tool_calls: number; turns: number; duration_s: number };
export type Episode = {
  episode_id: string;
  scenario_id: string;
  attempt: number;
  passed: boolean;
  error: string | null;
  checks: Check[];
  totals: Totals;
};

export type TrajectoryEvent = {
  t: number;
  type: string;
  turn?: number;
  content?: string;
  model?: string;
  api?: string;
  stream?: boolean;
  cache?: string;
  tokens_in?: number;
  tokens_out?: number;
  latency_ms?: number;
  tool_calls?: string[];
  server?: string;
  tool?: string;
  args?: Record<string, unknown>;
  is_error?: boolean;
  injected?: boolean;
  blocked?: boolean;
  mocked?: boolean;
  error?: string;
  message?: string;
};

export type ComparisonRow = {
  scenario_id: string;
  base_passed: number;
  base_n: number;
  cand_passed: number;
  cand_n: number;
  delta: number;
  p_adj: number;
  verdict: "regressed" | "improved" | "inconclusive" | "unchanged";
  runs_needed?: number | null;
};

export type RunDetail = {
  run: Run;
  progress?: Run["progress"] | null;
  scenarios?: { id: string; n: number; passed: number; pass_rate: number; flaky: boolean }[];
  summary?: {
    pass_at_1: number;
    pass_at_1_ci: [number, number];
    pass_pow_k: number;
    pass_at_k: number;
    k: number;
    n_episodes: number;
    tokens_per_episode: number;
    duration_p50_s: number;
    duration_p95_s: number;
    flaky_scenarios: string[];
    errors: number;
  };
  episodes?: Episode[];
  scenario_meta?: Record<string, { description: string; tags: string[] }>;
  failures?: { scenario_id: string; attempt: number; error: string | null; failed_checks: string[] }[];
  comparison?: {
    overall: { verdict: string; delta: number; ci: [number, number] };
    counts: Record<string, number>;
    scenarios: ComparisonRow[];
  };
};

export type Finding = { suite: string; severity: string; title: string; detail: string; tool: string | null };
export type Audit = {
  id: number;
  server: string;
  grade: string;
  overall: number;
  created_at: string;
  report?: { findings: Finding[]; scores: Record<string, number>; tools: { name: string; description: string }[]; metrics: Record<string, unknown> };
};

export class ApiError extends Error {
  status: number;
  constructor(message: string, status = 0) {
    super(message);
    this.status = status;
  }
}

/** Fired when the server says the session is missing or expired, so the shell can show the login screen. */
export const UNAUTHORIZED = "crucible:unauthorized";

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  let r: Response;
  try {
    r = await fetch(`${API}${path}`, {
      ...init,
      credentials: "include", // session cookie set by /api/auth/login
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("offline");
  }
  if (!r.ok) {
    let msg = `${r.status}`;
    try {
      const body = await r.json();
      msg = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body);
    } catch {}
    if (r.status === 401 && !path.startsWith("/api/auth/")) window.dispatchEvent(new Event(UNAUTHORIZED));
    throw new ApiError(msg, r.status);
  }
  return r.json();
}

export const reportUrl = (id: string) => `${API}/api/runs/${id}/report`;
