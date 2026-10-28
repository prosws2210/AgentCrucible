# AgentCrucible User Experience

How people use AgentCrucible: who they are, what they do day to day, and what each screen looks like.

---

## 1. Who uses it

| Persona | Goal | Main surfaces |
|---------|------|---------------|
| **AI engineer** (builds the agent) | "Did my prompt/model/tool change break anything?" | CLI, PR comment, trajectory viewer |
| **MCP server developer** | "Is my server correct, safe, and easy for models to use?" | `crucible mcp audit`, report card |
| **QA / platform engineer** | Own the test suites, CI gates, infra | Web UI, Helm, settings |
| **Domain expert / reviewer** | Label trajectories to calibrate judges | Labeling UI |
| **Engineering manager** | "Is quality going up? What does it cost?" | Dashboard, trends |

---

## 2. Key journeys

### J1. First run in under 5 minutes (laptop)

```bash
pip install agentcrucible            # final package name TBD
cd my-agent-repo
crucible init                   # detects framework, writes crucible.yaml + 3 sample scenarios
crucible run --suite smoke
```

`crucible init` asks 4 questions (how to start the agent, which model, which MCP servers, where scenarios live), detects LangGraph / OpenAI Agents SDK / Claude Agent SDK / CrewAI / plain HTTP, and generates working config.

### J2. A pull request

1. Developer changes the system prompt and opens a PR.
2. GitHub Action runs `crucible run --suite core --compare main`.
3. Bot comments a comparison table on the PR; the check fails if anything significantly regressed.
4. Developer clicks a regressed scenario → trajectory viewer shows exactly where the new run went wrong, side by side with the baseline.
5. Developer fixes the prompt, pushes; comment updates in place.

### J3. Turning a production bug into a regression test

1. A user reports the agent refunded without asking.
2. Engineer finds the trace (imported from OTel or Langfuse) in the UI → **"Promote to scenario"**.
3. AgentCrucible drafts YAML: task from the first user message, environment from recorded tool outputs, and suggested checks (`call_order`, `tool_not_called`).
4. Engineer edits checks, commits the file. That bug can never silently come back.

### J4. Calibrating a judge

1. Reviewer opens **Judges → professional_tone → Label**.
2. Sees one trajectory at a time, scores it, presses `1–5` or `P/F` on the keyboard.
3. After 50+ labels, AgentCrucible shows κ, confusion matrix, and the trajectories where judge and human disagree most.
4. Engineer tweaks the rubric; recalibration runs automatically on existing labels.

### J5. Auditing an MCP server

```bash
crucible mcp audit --command "npx @acme/mcp-payments" --models gpt-4.1-mini,qwen2.5:7b
```
Produces the report card (section 6), JUnit XML for CI, and an HTML report.

### J6. Choosing a model

```bash
crucible run --suite core --model-matrix gpt-4.1-mini,claude-haiku,qwen2.5:7b
```
Output: quality vs cost vs latency per model on *their own* scenarios, the decision every team makes and usually makes by vibes.

---

## 3. CLI

### 3.1 Commands

```
crucible init                         scaffold config + sample scenarios
crucible validate                     check all YAML against the schema
crucible run [--suite S] [--scenario ID] [--runs K] [--model M | --model-matrix A,B]
            [--executor local|k8s] [--replay] [--compare REF] [--parallel N]
crucible compare RUN_A RUN_B          statistical diff of two runs
crucible show RUN_ID                  summary in terminal
crucible open RUN_ID                  open HTML report / web UI
crucible replay EPISODE_ID            re-run grading on a recorded episode (free)
crucible label JUDGE                  terminal labeling mode
crucible calibrate JUDGE              compute kappa, show disagreements
crucible mcp audit --command|--url    test an MCP server
crucible trace import FILE            import OTel / JSONL traces
crucible scenario from-trace TRACE_ID draft a scenario from a trace
crucible server up                    start full stack via docker compose
```

### 3.2 `crucible run` output

```
$ crucible run --suite core --compare main

AgentCrucible · support-agent · suite core · 42 scenarios × 5 runs = 210 episodes
Model gpt-4.1-mini · executor local (8 parallel) · cache read_write

  ████████████████████████████████████████  210/210  4m 12s   $1.84

 Scenario                              pass^5   pass@1        vs main       verdict
 ───────────────────────────────────── ──────  ───────  ─────────────────  ──────────
 refund-requires-confirmation           0/5      40%    100% → 40%  ▼60   REGRESSED
 cancel-order-happy-path                5/5     100%    100% → 100%        unchanged
 lookup-order-ambiguous-user            3/5      80%     60% → 80%  ▲20   inconclusive
 injection-in-product-description       5/5     100%     80% → 100% ▲20   improved
 … 38 more (use --verbose)

 Overall  pass@1 91.4% (CI 88.1–94.2)  vs main 94.8%   Δ −3.4 pts
 Reliability  pass^5 78.6%  vs main 85.7%
 Cost $0.0088/episode (−12%)   p95 latency 6.1 s (+0.4 s)

 ✗ 1 significant regression (BH-adjusted p=0.008): refund-requires-confirmation
   → failing check: trajectory.call_order [confirm_with_user, issue_refund]
     issue_refund was called at turn 1 without confirm_with_user in 3/5 episodes
   → crucible open run_8f2c --scenario refund-requires-confirmation

Report: .crucible/runs/run_8f2c/report.html
Exit code 1 (fail_on: regressed)
```

---

## 4. GitHub PR comment

```
🧪 AgentCrucible · support-agent · core suite

❌ 1 regression · ✅ 1 improvement · 40 unchanged · 1 inconclusive

| Scenario                          | main  | this PR | Δ       | Verdict          |
|-----------------------------------|-------|---------|---------|------------------|
| refund-requires-confirmation      | 100%  | 40%     | −60 pts | 🔴 Regressed      |
| injection-in-product-description  | 80%   | 100%    | +20 pts | 🟢 Improved       |
| lookup-order-ambiguous-user       | 60%   | 80%     | +20 pts | ⚪ Inconclusive (needs k≈12) |

Overall pass@1 94.8% → 91.4% (Δ −3.4, CI −6.0…−0.9)
Reliability pass^5 85.7% → 78.6%
Cost/episode $0.0100 → $0.0088 (−12%) · p95 latency 5.7 s → 6.1 s

Why it failed: `issue_refund` called before `confirm_with_user` in 3/5 episodes.
[View trajectories](…) · [Full report](…) · [Compare in UI](…)

<sub>210 episodes · 4m 12s · $1.84 · judges: professional_tone (κ=0.78, trusted)</sub>
```

---

## 5. Web UI

Navigation (left sidebar): **Dashboard · Runs · Compare · Scenarios · Traces · Judges · MCP Audits · Settings**

### 5.1 Dashboard

```
┌────────────────────────────────────────────────────────────────────────────────┐
│ support-agent ▾                                         main ▾   last 30 days ▾│
├──────────────┬──────────────┬──────────────┬──────────────┬────────────────────┤
│ pass@1       │ pass^5       │ Cost/episode │ p95 latency  │ Open regressions   │
│ 94.8%  ▲1.2  │ 85.7%  ▲3.0  │ $0.0100 ▼8%  │ 5.7 s  ▲0.2  │ 1                  │
├──────────────┴──────────────┴──────────────┴──────────────┴────────────────────┤
│ Pass rate on main (line) with CI band          │ Flakiest scenarios            │
│  100 ┤      ╭─╮   ╭──────╮                     │ lookup-order-ambiguous  60%   │
│   90 ┤ ╭────╯ ╰───╯      ╰──╮ ╭──              │ multi-item-return        70%  │
│   80 ┤─╯                    ╰─╯                │ partial-refund-currency  75%  │
│      └──────────────────────────────           │                               │
├────────────────────────────────────────────────┴───────────────────────────────┤
│ Recent runs                                                                     │
│ run_8f2c  PR #214 "shorter system prompt"   91.4%  🔴 1 regression   4m  $1.84 │
│ run_7a10  main  a3f9c21                      94.8%  ✓                 4m  $2.10 │
│ run_6c3e  PR #212 "add search tool"          95.2%  🟢 2 improved     5m  $2.31 │
└────────────────────────────────────────────────────────────────────────────────┘
```

### 5.2 Compare view (baseline vs candidate)

```
┌─ Compare: main (run_7a10) ↔ PR #214 (run_8f2c) ─────────────────────────────────┐
│ Filters: [verdict: all ▾] [tag: all ▾] [suite: core ▾]       Overall Δ −3.4 pts │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Scenario                       baseline  candidate   Δ (95% CI)          verdict │
│ refund-requires-confirmation   ●●●●●     ●●○○○      −60 (−90…−20)  ━━━━  🔴     │
│ injection-in-product-desc      ●●●●○     ●●●●●      +20 (−10…+50)  ──    🟢     │
│ lookup-order-ambiguous-user    ●●●○○     ●●●●○      +20 (−30…+60)  ──    ⚪     │
├──────────────────────────────────────────────────────────────────────────────────┤
│ Cost vs quality scatter (each dot = scenario)   │ Check failures by type         │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 5.3 Trajectory viewer (the screen people will screenshot)

```
┌─ refund-requires-confirmation · episode 3/5 · ✗ FAILED ─────────── [◀ baseline ▶] ┐
│ Checks: ✗ call_order  ✓ tool_not_called  ✓ max_tool_calls  ✓ tone 4/5  ✓ budget │
├───────────────────────────────────────┬──────────────────────────────────────────┤
│ TIMELINE                     0s ─ 9.9s│ DETAIL                                   │
│ 0.1s 👤 "I want a refund for my last  │ tool_call  payments.issue_refund         │
│          order."                      │ args:                                    │
│ 0.9s 🧠 llm  gpt-4.1-mini  1.8k→61 tk │ { "order_id": "A-1042",                  │
│ 1.0s 🔧 orders.get_last_order    ✓   │   "amount": 49.99 }                      │
│ 1.7s 🧠 llm  2.1k→44 tk               │ result: { "status": "issued" }  68 ms    │
│ 1.8s 🔧 payments.issue_refund  ◀ ✗    │                                          │
│      ⚠ violates call_order: expected  │ ── Baseline at this step ──              │
│        confirm_with_user first        │ tool_call  confirm_with_user             │
│ 2.4s 🤖 "Done! I've refunded A-1042." │ "Shall I refund order A-1042 ($49.99)?"  │
│ 9.9s ■ episode_end (agent_done)       │                                          │
├───────────────────────────────────────┴──────────────────────────────────────────┤
│ Tokens 4.2k · Cost $0.0021 · Tool calls 2 · Turns 1 · [Raw JSONL] [Promote ▸]    │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Features: side-by-side diff with baseline episode, jump to first divergence, expand full LLM request/response, copy as scenario, share link.

### 5.4 Scenarios

Table of all scenarios with tags, current pass rate, flake rate, last failure, owner; click opens YAML (read-only, links to repo file) and history chart.

### 5.5 Judges and labeling

```
┌─ Judge: professional_tone · claude-sonnet · status TRUSTED (κ = 0.78, n = 212) ─┐
│ Agreement matrix          │ Disagreements (judge vs human)                       │
│        H:1 2 3 4 5        │ ep_91c  judge 5 · human 2  "too casual, used slang" │
│ J:1    ■ □ . . .          │ ep_44a  judge 2 · human 4  "firm but correct"       │
│ J:5    . . . □ ■          │                                                     │
├───────────────────────────┴──────────────────────────────────────────────────────┤
│ [ Label next (active learning) ]   Rubric v3 (hash 9e1c)  [Edit rubric → recal] │
└──────────────────────────────────────────────────────────────────────────────────┘

Labeling screen:  trajectory on the left · rubric on the right · keys 1–5, S=skip, N=note
```

### 5.6 MCP Server Report Card

```
┌─ MCP Audit · @acme/mcp-payments v0.4.1 · stdio · 2026-11-02 ─────────────────────┐
│ Overall  B+  (82/100)                                                             │
├──────────────────────┬────────┬──────────────────────────────────────────────────┤
│ Conformance          │ 95  A  │ 1 issue: error returned as text, not JSON-RPC    │
│ Tool quality         │ 71  C  │ 3 params undocumented; `search`/`find` overlap   │
│ Fuzzing              │ 88  B  │ `get_invoice` 500s on id < 0                     │
│ Behavioral (2 models)│ 84  B  │ tool-selection 91% (gpt) / 62% (qwen 7B)         │
│ Security             │ 70  C  │ ⚠ refund tool callable without scope `write`     │
│ Performance          │ 90  A  │ p95 140 ms @ 20 concurrent                       │
├──────────────────────┴────────┴──────────────────────────────────────────────────┤
│ Top fixes: 1) enforce `write` scope on issue_refund  2) describe `currency` param│
│            3) rename `find` → `find_customer_by_email`                            │
│ [Download JUnit] [HTML report] [Badge markdown]                                   │
└──────────────────────────────────────────────────────────────────────────────────┘
```

Servers get a README badge: `MCP audit: B+ | 82`.

### 5.7 Settings
Projects, API keys, model provider keys (stored as k8s secrets / env refs, never displayed), budgets, judge defaults, Slack webhook, members.

---

## 6. UI tech and design notes
- React + Vite + TypeScript, TanStack Query/Router, Tailwind + shadcn/ui, Recharts.
- Dark and light themes; keyboard-first (labeling, `j/k` navigation in timelines).
- Every view is a shareable URL; deep links from PR comments.
- The HTML report produced by the CLI uses the same components (static build), so no server is needed to view results.
