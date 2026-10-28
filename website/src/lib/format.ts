export const pct = (x: number | null | undefined) => (x == null || Number.isNaN(x) ? "–" : `${Math.round(x * 100)}%`);

export const signedPts = (x: number) => `${x >= 0 ? "+" : "−"}${Math.abs(x * 100).toFixed(1)} pts`;

export function when(iso: string) {
  return new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function ago(iso: string) {
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)} min ago`;
  if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return `${Math.floor(s / 86400)} d ago`;
}

export function duration(seconds: number) {
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  const m = Math.floor(seconds / 60);
  return `${m}m ${Math.round(seconds % 60)}s`;
}

/** Plain-language names for check types, shown next to the technical label. */
export const CHECK_HELP: Record<string, string> = {
  "state.sql": "database ends in the expected state",
  "http.called": "calls the external API it should",
  "http.not_called": "never calls an external API it shouldn't",
  "state.command": "command in the repo succeeds (e.g. tests)",
  "state.git_diff": "only the expected files change",
  "state.file": "file contents are as expected",
  "trajectory.tool_called": "uses a required tool",
  "trajectory.tool_not_called": "never uses a forbidden tool",
  "trajectory.call_order": "uses tools in the right order",
  "trajectory.not_before_turn": "waits for the user before acting",
  "trajectory.max_tool_calls": "stays within the tool-call limit",
  "trajectory.no_tool_errors": "no tool returns an error",
  "trajectory.no_blocked_calls": "never tries a blocked tool",
  "output.contains": "reply mentions the expected text",
  "output.not_contains": "reply never contains forbidden text",
  "output.regex": "reply matches the expected pattern",
  "budget.max_llm_calls": "stays within the LLM-call budget",
  "budget.max_tokens": "stays within the token budget",
  "budget.max_duration_s": "stays within the time budget",
  "budget.max_cost_usd": "stays within the cost budget",
  "judge.rubric": "LLM judge scores it highly enough",
};
