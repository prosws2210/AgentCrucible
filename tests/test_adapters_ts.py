"""TypeScript agents through the @agentcrucible/adapters runtime, with the real Vercel AI SDK and Mastra.

discover -> apply -> smoke run against a scripted model: the run must pass and the tool's call and result must reach
the trajectory through the runtime's tracing. Needs Node and a folder with the libraries installed:

    npm install ai @ai-sdk/openai @mastra/core zod tsx       # in some folder, then
    CRUCIBLE_TS_DEPS=/that/folder pytest tests/test_adapters_ts.py

Skipped otherwise. The runtime copy shipped in the Python package must match packages/adapters-js (checked always).
"""

import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import pytest
import uvicorn
from test_adapters_frameworks import fake_model

from agentcrucible.discover import apply, build_plan, discover
from agentcrucible.gateway import free_port
from agentcrucible.trajectory import load_events

ROOT = Path(__file__).resolve().parent.parent

CASES = {
    "vercel-ai": ("lib/agent.ts", '''import { generateText, stepCountIs, tool } from "ai";
import { openai } from "@ai-sdk/openai";
import { z } from "zod";

export const tools = {
  get_weather: tool({
    description: "Get the current weather for a city.",
    inputSchema: z.object({ city: z.string() }),
    execute: async ({ city }) => `It is sunny and 21C in ${city}.`,
  }),
};

export async function answerWeather(message: string) {
  const r = await generateText({ model: openai.chat("gpt-4o-mini"), system: "You answer weather questions.", prompt: message, tools, stopWhen: stepCountIs(5) });
  return r.text;
}
'''),
    "mastra": ("src/agents/weather.ts", '''import { Agent } from "@mastra/core/agent";
import { createTool } from "@mastra/core/tools";
import { z } from "zod";

export const getWeather = createTool({
  id: "get_weather",
  description: "Get the current weather for a city.",
  inputSchema: z.object({ city: z.string() }),
  execute: async ({ city }) => `It is sunny and 21C in ${city}.`,
});

export const weatherAgent = new Agent({
  id: "weather",
  name: "Weather",
  instructions: "You answer weather questions.",
  model: "openai/gpt-4o-mini",
  tools: { get_weather: getWeather },
});
'''),
}


def test_bundled_runtime_matches_the_package():
    pkg = (ROOT / "packages" / "adapters-js" / "src" / "index.ts").read_text(encoding="utf-8")
    bundled = (ROOT / "src" / "agentcrucible" / "adapters" / "runtime" / "crucible.ts").read_text(encoding="utf-8")
    assert pkg == bundled, "copy packages/adapters-js/src/index.ts to src/agentcrucible/adapters/runtime/crucible.ts"


@pytest.fixture(scope="module")
def model_url():
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(fake_model(), host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=server.run, daemon=True)
    th.start()
    while not server.started:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/v1"
    server.should_exit = True
    th.join(5)


@pytest.mark.parametrize("framework", list(CASES))
def test_ts_adapter(model_url, framework):
    deps = os.environ.get("CRUCIBLE_TS_DEPS")
    if not deps or not (Path(deps) / "node_modules").is_dir() or not shutil.which("npx"):
        pytest.skip("set CRUCIBLE_TS_DEPS to a folder with ai, @ai-sdk/openai, @mastra/core, zod and tsx installed")
    repo = Path(deps) / f"case-{framework}-{uuid.uuid4().hex[:6]}"  # inside it, so node finds node_modules above
    try:
        rel, code = CASES[framework]
        (repo / rel).parent.mkdir(parents=True)
        (repo / rel).write_text(code, encoding="utf-8")
        (repo / "package.json").write_text('{"name": "case", "private": true, "type": "module"}', encoding="utf-8")
        d = discover(repo)
        agents = [a for a in d.agents if a.include]
        assert len(agents) == 1 and agents[0].framework == framework, [(a.name, a.framework) for a in d.agents]
        assert agents[0].tools == ["get_weather"]
        build_plan(d, repo)
        assert d.plans[0].strategy == "code" and d.plans[0].command.startswith("npx tsx")
        d.scenarios = [s for s in d.scenarios if s.id.endswith("-uses")]
        rep = apply(d, repo, model="fake-model", upstream=model_url)["reality"]
        run_dir = repo / "agent-tests" / ".crucible" / "runs" / rep["run_id"]
        logs = "".join(p.read_text(encoding="utf-8", errors="replace")[-1500:] for p in (run_dir / "logs").glob("*.log"))
        assert rep["errors"] == 0 and rep["passed"] == rep["episodes"] >= 1, ([(s["error"], s["failed"]) for s in rep.get("scenarios", [])], rep["findings"], logs)
        run = json.loads((run_dir / "run.json").read_text())
        events = load_events(run_dir / run["episodes"][0]["trajectory"])
        traced = [e for e in events if e["type"] == "tool_result" and e["tool"] == "get_weather" and e.get("source") == "trace"]
        assert traced and "sunny" in traced[0]["content"], ([e for e in events if e["type"].startswith("tool")], logs)
    finally:
        shutil.rmtree(repo, ignore_errors=True)
