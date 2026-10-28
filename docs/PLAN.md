# Build Plan

> **Status 2026-10-28: v0.1 built (one-week, zero-cost scope).** Shipped: gateways, sandboxed runner, user
> simulator, all check types, stats engine + gate, HTML/Markdown reports, MCP audit (6 suites), judge
> calibration, sharded Kubernetes Helm chart (tested on kind), GitHub Action + CI, 14 tests. Real results in
> [RESULTS.md](./RESULTS.md).
>
> Changes from the original 12-week plan below: name **AgentCrucible** (earlier names `crucible` and `agentcrucible` were dropped); local Ollama
> instead of paid APIs; process-level sandbox instead of container-per-episode; static HTML report instead of
> a server + React UI; MCP SDK 1.x (2.x on the roadmap). Remaining for the week: push to GitHub, human labels
> for judge calibration, demo video, write-up.
>
> The original plan follows for reference.

# AgentCrucible Build Plan (original)

Companion docs: [ARCHITECTURE.md](./ARCHITECTURE.md) · [USER-EXPERIENCE.md](./USER-EXPERIENCE.md)

**Goal:** ship v0.1 of an open-source, framework-agnostic regression testing platform for AI agents and MCP servers that any company can install. Publish a benchmark and write-up that become the centerpiece of your resume.

**Timeline:** 12 weeks at ~20–25 hours/week (Phase 0 is 2–3 days).
**Today:** 2026-10-28 → target v0.1 launch around **late January 2027**.

---

## 1. What "done" looks like (v0.1)

- [ ] `pip install <name>` → `crucible init` → `crucible run` works on a LangGraph agent, an OpenAI Agents SDK agent and a plain HTTP agent **without changing their code**
- [ ] Record/replay through LLM Gateway + MCP Gateway; replayed re-grades cost $0
- [ ] State, trajectory, output, judge, budget and policy checks
- [ ] pass@k, pass^k, paired bootstrap CIs, BH-corrected regression verdicts
- [ ] Judge calibration with κ; untrusted judges can't fail CI
- [ ] GitHub Action with upserted PR comment + JUnit output
- [ ] Web UI: dashboard, compare, trajectory viewer, judges/labeling, MCP report card
- [ ] Kubernetes executor + Helm chart + KEDA + NetworkPolicy; runs 1,000+ episodes in parallel on `kind`
- [ ] `crucible mcp audit` with 6 suites + report card + badge
- [ ] Public benchmark: ~150 scenarios × 4 models × 5 runs, with written findings
- [ ] Docs site, blog post, 3–5 min demo video, v0.1 release on PyPI + GHCR

---

## 2. Phases

### Phase 0: Setup (2–3 days)
| Task | Owner |
|------|-------|
| Make decisions D1–D8 (section 4) | **You** |
| Install `kind`, `helm`; pull Ollama models | **You** (commands in section 5) |
| Create GitHub repo, enable Actions + GHCR | **You** (I can do it with `gh` once you approve) |
| Monorepo scaffold: `uv` workspace, ruff, mypy, pytest, pre-commit, Makefile, CI workflow | Claude |
| `docs/design.md` decision log started | Claude |

**Exit:** `make test` passes in CI on an empty skeleton.

---

### Phase 1: Core engine, local only (Weeks 1–3) → **MVP**
| Week | Build | Acceptance test |
|------|-------|-----------------|
| **1** | `core`: Pydantic models for project config, scenario, checks, trajectory events; JSON Schema export; `crucible validate`. Example **MCP servers** (orders, payments, files) with deliberately planted bugs; example **plain-Python agent** speaking the HTTP Agent Contract | `crucible validate` passes on 10 scenarios; example agent answers via `curl` |
| **2** | **LLM Gateway** v1 (OpenAI-compatible passthrough, record tokens/cost/latency, cache) + **MCP Gateway** v1 (HTTP + stdio, record all calls). **Local executor** (Docker network per episode, Postgres fixture, env injection) | One scenario runs end to end; trajectory JSONL contains every LLM and tool call |
| **3** | Deterministic **graders** (state.sql, trajectory.*, output.*, budget.*); runner with parallelism; terminal summary + static **HTML report**; `crucible run` | `crucible run --suite smoke` on example agent; failing scenario shows which check failed and why |

**MVP checkpoint (end of week 3):** you demo `crucible run` to yourself on the example agent. We review architecture before going further.

---

### Phase 2: Comparison, determinism, CI (Weeks 4–5)
| Week | Build | Acceptance test |
|------|-------|-----------------|
| **4** | **Stats engine**: pass@1, pass@k, pass^k, paired bootstrap, Fisher + Benjamini–Hochberg, "runs needed" estimate. `crucible compare`. Baseline storage (local `.crucible/` + GitHub artifact). **Replay mode** for both gateways | Deliberately broken prompt → flagged `regressed`; random noise at k=5 → **not** flagged (tested by simulation) |
| **5** | **User simulator** (persona, max turns, pinned seed). **GitHub Action** + upserted PR comment + JUnit XML. Model override + model matrix | Demo PR in the repo fails the check with the table from USER-EXPERIENCE §4; matrix run compares 3 models |

> **Recommended:** you write the stats engine yourself (I review and write tests). It's the part interviewers will probe hardest, and owning it makes every number in your write-up defensible.

---

### Phase 3: Judges, security, robustness (Weeks 6–7)
| Week | Build | Acceptance test |
|------|-------|-----------------|
| **6** | **LLM judge** checks (rubric, pairwise, reference). **Labeling** (CLI first: `crucible label`). **Calibration**: κ, confusion matrix, trusted/advisory/disabled status, rubric-hash tracking | 200+ human labels across 3 rubrics; κ reported; low-κ judge auto-demoted |
| **7** | **Security suite**: injection payload library inserted via MCP Gateway; `policy.*` checks. **Fault injection** (LLM 429/500/timeouts; tool errors/latency/malformed output). **Secret redaction** | Attack-success-rate table per model; agent retry behavior visible in trajectories; no secret appears in stored trajectories (test) |

**You do the labeling** this phase: ~6–8 hours total, best in 45-minute blocks.

---

### Phase 4: Server, UI, Kubernetes (Weeks 8–9)
| Week | Build | Acceptance test |
|------|-------|-----------------|
| **8** | **API server** (FastAPI, Postgres, Alembic, MinIO, NATS), scheduler, hybrid upload mode. **Web UI**: dashboard, runs, compare, trajectory viewer, labeling screen. `docker compose` full stack | `crucible server up` → CLI run appears in UI; trajectory viewer shows side-by-side baseline diff |
| **9** | **Kubernetes executor** (Job per episode, sidecars, NetworkPolicy default-deny, limits, TTL). **Helm chart**, KEDA on queue depth. OpenTelemetry + Prometheus + Grafana for the platform itself | `helm install` on `kind`; 1,000 episodes (cached LLM) run in parallel; egress to non-allowed hosts blocked (test) |

---

### Phase 5: MCP audit mode + adapters (Weeks 10–11)
| Week | Build | Acceptance test |
|------|-------|-----------------|
| **10** | `crucible mcp audit`: conformance, tool-quality lint, Hypothesis schema fuzzing, behavioral (reference agent × models), security probes, performance. **Report card** UI + HTML + badge | Audit finds every bug planted in the example MCP servers; run on 3–5 popular public MCP servers |
| **11** | **SDK adapters**: LangGraph, OpenAI Agents SDK (Python); Vercel AI SDK (TS) as stretch. **Trace import** (OTel GenAI / JSONL) + **promote trace to scenario** | 3 example agents in `examples/` pass with zero code changes (L1) and richer traces with adapters (L2) |

---

### Phase 6: Benchmark and launch (Week 12)
| Task | Owner |
|------|-------|
| Run public benchmark: ~150 scenarios × 4 models × 5 runs (mostly cached / local models) | Claude runs, **you** sanity-check results |
| Write findings (single-run overstatement vs pass^5, judge reliability by criterion, injection rates, tool-selection on small models) | Claude drafts, **you** rewrite in your voice |
| Optional: deploy demo to a real cluster with Terraform + ArgoCD | Claude, needs D6 |
| Docs site (MkDocs), README with results table first | Claude |
| Record demo video (3–5 min) | **You** (script provided) |
| Release v0.1 to PyPI + GHCR (signed images) | Claude prepares, **you** approve publish |
| LinkedIn carousel + blog post + Show HN / r/LocalLLaMA / MCP Discord | **You** post (drafts provided) |

---

## 3. How we'll work

- **One GitHub issue per task**, one branch + PR per feature, CI must be green. AgentCrucible tests itself with AgentCrucible from Phase 2 onward.
- **I write most of the code; you review every PR** and run it locally. Before each PR merges I explain the design in a short note you can retell in an interview.
- **Weekly checkpoint (30 min):** demo what works, review the next week's issues, adjust scope.
- **Scope rule:** if a week slips, cut from Phase 5 stretch items (TS adapter, Rust gateway, cloud deploy), never from tests or the benchmark.
- **Honesty rule:** every number in the README must come from a script in `benchmarks/` that anyone can rerun.

---

## 4. Decisions I need from you

| # | Decision | Options | My recommendation |
|---|----------|---------|-------------------|
| **D1** | Package / product name (`crucible` is taken on PyPI and npm) | `agentcrucible` (free on both), or your own idea; I'll check availability | Pick something memorable; keep "AgentCrucible" only as a description |
| **D2** | License | Apache-2.0, MIT, AGPL | **Apache-2.0**: companies can adopt it, patent grant included |
| **D3** | Public from day 1? | Public repo now, or private until v0.1 | **Public from week 1**: commit history is itself evidence |
| **D4** | Model providers | OpenRouter (one key, many models), OpenAI, Anthropic, Groq (free tier), local Ollama | **OpenRouter + Ollama**: one bill, plus free local runs |
| **D5** | API budget for 12 weeks | — | **$40–80** total (caching + local models keep it low) |
| **D6** | Real cloud demo? | `kind` only (free), or a managed cluster for ~1 week (DigitalOcean / Civo / Azure student credits) | `kind` for development, cloud only for the final demo week |
| **D7** | Hours per week | — | 20–25 h/week fits the 12-week plan; 10–15 h → plan becomes ~20 weeks |
| **D8** | Example agent domain | E-commerce support (default), finance ops (fits FilingLens/GeniusCFO), healthcare intake (fits JIPMER) | **E-commerce support** for clarity; finance agent as the second example |

---

## 5. Setup checklist (things on your machine and accounts)

**Already installed:** Docker 29, kubectl 1.36, Python 3.13, uv, Node 24, git, gh, Ollama. Hardware: 15 GB RAM, RTX 4050 (6 GB).

**To install**
```powershell
winget install Kubernetes.kind
winget install Helm.Helm
ollama pull qwen2.5:7b        # ~4.7 GB, fits 6 GB VRAM (Q4); main local test model
ollama pull llama3.2:3b       # small/fast model for simulator + cheap runs
```

**Docker Desktop settings:** give it at least **8 GB RAM** and 4 CPUs (Settings → Resources), WSL 2 backend on.

**Accounts / keys** (put them in a local `.env` that is git-ignored; never paste keys in chat)
| Item | Needed for | When |
|------|------------|------|
| GitHub repo + `gh auth login` | Code, Actions, GHCR images | Phase 0 |
| OpenRouter API key (or OpenAI) | Agent + judge models | Week 2 |
| Anthropic key (optional) | Judge diversity | Week 6 |
| Groq key (optional, free tier) | Fast cheap runs | Any time |
| PyPI account + trusted publishing | v0.1 release | Week 12 |
| Cloud account (optional, D6) | Final demo cluster | Week 12 |

**Your time beyond reviews**
| Activity | Time |
|----------|------|
| Weekly checkpoint | 30 min/week |
| PR reviews + running things locally | 4–6 h/week |
| Writing the stats engine (recommended) | ~8 h in week 4 |
| Labeling for judge calibration | 6–8 h in weeks 6–7 |
| Benchmark sanity check + write-up in your voice | ~6 h in week 12 |
| Demo video | ~3 h in week 12 |

---

## 6. Budget

| Item | Estimate |
|------|----------|
| LLM API (development + benchmark, with caching) | $40–80 |
| Local models (Ollama on your GPU) | $0 |
| `kind` cluster | $0 |
| Optional managed cluster for demo week | $0–30 (free with student/trial credits) |
| Domain for docs site (optional) | ~₹800/yr |

---

## 7. Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Scope too big for 12 weeks | High | MVP at week 3 is already demo-able; Phase 5 stretch items are cuttable |
| 15 GB RAM tight for `kind` + Postgres + models | Medium | Run Ollama on host (GPU), keep `kind` single-node, mock LLM for scale tests |
| MCP spec keeps changing | Medium | Gateway isolates spec versions; version matrix in config |
| Judge labels inconsistent | Medium | Write rubric examples first; label in short blocks; measure your own consistency on 20 repeats |
| API costs | Low | Cache by default, replay for re-grades, local models for bulk runs, hard budgets in gateway |
| "AI wrote it" perception in interviews | Medium | You own the stats engine, review every PR, keep a design decision log, can explain each trade-off |

---

## 8. Success metrics (beyond the resume)

- 3 example agents in different frameworks pass with zero code changes
- 5+ public MCP servers audited, with issues filed upstream (real-world validation)
- First external user or contributor
- 100+ GitHub stars within a month of launch (stretch)
- Benchmark findings cited or shared by others

---

## 9. Immediately after you answer section 4

1. I scaffold the monorepo in `E:\projects\resume-projects\crucible` (Phase 0).
2. I create the GitHub repo and the 12-week issue board (with your approval).
3. Week 1 starts: core schema + example MCP servers + example agent.
