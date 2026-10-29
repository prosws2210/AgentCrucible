# Import benchmark: 10 open-source agent repositories

`benchmarks/import_bench.py` imports real repositories (pinned commits in `repos.json`) the way a user does: scan with
the local model writing descriptions, apply the reviewer's edits recorded for that repository (none were needed), write
the tests and smoke-run each once. Their code runs in a throwaway container (`benchmarks/Dockerfile`); the model is
qwen2.5:7b on Ollama on the same machine, at 50–80 s per call during these runs.

## Results (final code)

| Repository | Framework | Agents tested | Questions | Edits | Path → smoke run | Smoke run | Main cause of failures |
|---|---|---|---|---|---|---|---|
| [react-agent](https://github.com/langchain-ai/react-agent) `87aac0fdcb81` | LangGraph | 1 | 2 | 0 | 8.0 min | 3/4 passed, 0 agent errors | agent behaviour: one check failed |
| [retrieval-agent-template](https://github.com/langchain-ai/retrieval-agent-template) `1d0c84cf19a6` | LangGraph (RAG) | 2 | 1 | 0 | 2.4 min | 0/2 passed, 2 agent errors | its retriever needs Elasticsearch, Pinecone or MongoDB credentials (called from a graph node, so tests can't mock it) |
| [memory-agent](https://github.com/langchain-ai/memory-agent) `eb23fc1177ab` | LangGraph (memory) | 1 | 1 | 0 | 5.6 min | 0/1 passed, 1 agent errors | the model passes `user_id` in the tool call, which the agent's code also sets |
| [data-enrichment](https://github.com/langchain-ai/data-enrichment) `dd0c92220f23` | LangGraph | 1 | 1 | 0 | 28.2 min | 0/7 passed, 7 agent errors | multi-step research turns take over 10 min on this model and time out |
| [openai-cs-agents-demo](https://github.com/openai/openai-cs-agents-demo) `bd7bfca0f5ab` python-backend | OpenAI Agents SDK (multi-agent) | 8 | 3 | 0 | 37.0 min | 3/16 passed, 13 agent errors | 8 turns time out on this model; the others are the agents' answers |
| [openai-agents-customer-service](https://github.com/openai/openai-agents-python) `cd26bbbc5284` | OpenAI Agents SDK | 1 | 3 | 0 | 6.1 min | 0/4 passed, 0 agent errors | agent behaviour: the triage agent answered without handing off |
| [crewai-trip-planner](https://github.com/crewAIInc/crewAI-examples) `da94a91e691e` crews/trip_planner | CrewAI | 2 | 5 | 0 | 10.6 min | 0/7 passed, 7 agent errors | the example imports `langchain.llms`, removed in LangChain 1.0 |
| [pydantic-ai-examples](https://github.com/pydantic/pydantic-ai) `c2ef90b6acbf` examples | PydanticAI | 5 | 3 | 0 | 14.2 min | 2/6 passed, 3 agent errors | twice the model's structured output didn't validate (the agent gave up); the bank example creates its database only when run as a script |
| [adk-cross-session-memory](https://github.com/google/adk-samples) `66c0c586136c` core/python/cross-session-memory | Google ADK | 1 | 0 | 0 | 4.8 min | 2/2 passed, 0 agent errors |  |
| [anthropic-agents](https://github.com/anthropics/anthropic-quickstarts) `12349bb27f86` agents | Raw Anthropic tool loop | 0 | 4 | 0 | 4.4 min | nothing to test (agents only in test files) |  |

**Summary:** 9 of 10 repositories reached a smoke run (the tenth correctly has nothing to test); 3 ran with no agent
errors, all in under 10 minutes; 10 of 49 drafted tests passed. **Edits per review: 0** (target < 5, met).
**Questions per repository: 2.3** (target < 5, met). The import itself (scan, plan, write, connection check) took
1–3 minutes everywhere; the rest is the smoke run.

The plan's Phase 1 target (10 repositories to a green smoke run in under 10 minutes, fewer than 5 edits) is **not met**
on this machine. What stands in the way, by repository:

- **Local model speed.** Multi-step turns of data-enrichment and openai-cs-agents-demo take over 10 minutes each with
  a 7B model at 50–80 s per call, and hit the per-turn limit (now 600 s). A faster model or a GPU changes this; the
  import itself takes 1–3 minutes.
- **Services the agent needs.** retrieval-agent-template calls Elasticsearch/Pinecone/MongoDB directly from a graph
  node (not through a tool the tests can mock) and needs real credentials.
- **The model, not the harness.** memory-agent crashes because qwen2.5:7b passes `user_id` in the tool arguments,
  which the agent's code also sets; pydantic-ai's structured-output agents give up when the model's output doesn't
  validate. These are the failures the tests exist to catch.
- **Examples that only run as scripts.** pydantic-ai's bank example builds its database in `if __name__ == "__main__"`,
  so importing the agent (what an adapter does) leaves it without one.
- **Out-of-date example.** crewAI-examples' trip planner imports `langchain.llms`, which LangChain 1.0 removed.
- **Nothing to test.** anthropic-quickstarts/agents is a small library whose only agent instances are in a test file;
  the import now says so instead of testing fixtures.

## What the benchmark fixed

The first pass ran the import as it was, on code its detectors had not been tuned on. It found:

- tools in a list imported from another module (`ToolNode(TOOLS)`), tools bound inside a graph node
  (`bind_tools([tools.x])`), generic agents (`Agent[Context](...)`), `handoff(agent=...)` calls, crew members built by
  factory methods: all missed or wrongly split, now detected (regression tests in `tests/test_discover_extras.py`);
- agents named after generic variables (`builder`, `agent`), and model-written questions the code already answers;
- adapters that ran agents without the context they declare (LangGraph `context_schema`, OpenAI Agents
  `Agent[Context]`, PydanticAI `deps_type`), without a store (LangGraph Platform injects one), or with a graph input that
  isn't a chat; no Google ADK adapter;
- agent crashes reported as answers that failed checks. In the first pass, react-agent, retrieval-agent-template and
  memory-agent looked green because the crash text matched the smoke test's "any reply" check; they were crashing.

First pass for comparison: 6 of 10 "without errors"
(inflated by the crash reporting above), react-agent found 0 tools (now 1), the customer-service example's agents only
through the generic fallback (now one triage agent with two handoffs).

Rerun: `docker build -f benchmarks/Dockerfile -t agentcrucible-bench . && docker run --rm --network agentcrucible_default
-v "$PWD/.bench:/work" agentcrucible-bench` (with `docker compose up` for the model server).
