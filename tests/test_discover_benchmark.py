"""Detector accuracy on an independently written corpus (tests/discover_corpus, plan section 14).

Each case is a small repository in one framework with hand-labelled agents, tools, side effects and MCP servers.
The targets are the plan's Phase 1 targets; the per-case table is printed so regressions are easy to locate.
"""

import json
import re
from pathlib import Path

import pytest

from agentcrucible.discover import discover

CORPUS = Path(__file__).resolve().parent / "discover_corpus"
CASES = sorted(p for p in CORPUS.iterdir() if (p / "expected.json").exists()) if CORPUS.exists() else []


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


ORCHESTRATORS = ("crew", "workflow")  # a Crew / AgentWorkflow runs the labelled agents; not a false agent, not one of them


def agent_names(d) -> list[set[str]]:
    out = []
    for a in d.agents:
        f0 = d.facts.get(a.evidence[0]) if a.evidence else None
        if f0 is not None and f0.attrs.get("role") in ORCHESTRATORS:
            continue
        f = d.facts.get(a.evidence[0]) if a.evidence else None
        attrs = f.attrs if f else {}
        names = {a.name, a.id, f.name if f else ""} | {str(attrs.get(k) or "") for k in ("object", "function", "factory", "config_key", "method", "compiled_as")}
        out.append({norm(n) for n in names if n})
    return out


def score_case(case: Path) -> dict:
    exp = json.loads((case / "expected.json").read_text(encoding="utf-8"))
    d = discover(case)
    found_agents = agent_names(d)
    exp_agents = [norm(a["name"]) for a in exp["agents"]]
    matched_agents = [a for a in exp_agents if any(a in names for names in found_agents)]
    agent_fp = [names for names in found_agents if not any(a in names for a in exp_agents)]
    found_tools = {norm(t.name): t for t in d.tools}
    exp_tools = {norm(k): set(v) for k, v in exp["tools"].items()}
    matched_tools = [t for t in exp_tools if t in found_tools]
    tool_fp = [t for t in found_tools if t not in exp_tools]
    effects_ok = [t for t in matched_tools if set(found_tools[t].effects) == exp_tools[t]]
    exp_servers = {norm(s) for s in exp.get("mcp_servers", [])}
    found_servers = {norm(s.name) for s in d.mcp_servers}
    return {
        "case": case.name,
        "agents": (len(matched_agents), len(exp_agents), len(agent_fp)),
        "tools": (len(matched_tools), len(exp_tools), len(tool_fp)),
        "effects": (len(effects_ok), len(matched_tools)),
        "servers": (len(exp_servers & found_servers), len(exp_servers)),
        "missing_agents": [a for a in exp_agents if a not in matched_agents],
        "extra_agents": [sorted(n)[0] for n in agent_fp],
        "missing_tools": [t for t in exp_tools if t not in found_tools],
        "extra_tools": tool_fp,
        "wrong_effects": {t: (sorted(found_tools[t].effects), sorted(exp_tools[t])) for t in matched_tools if t not in effects_ok},
    }


@pytest.mark.skipif(not CASES, reason="benchmark corpus not present")
def test_detector_benchmark(capsys):
    rows = [score_case(c) for c in CASES]
    tot = {k: [0, 0, 0] for k in ("agents", "tools")}
    eff = [0, 0]
    srv = [0, 0]
    for r in rows:
        for k in ("agents", "tools"):
            for i in range(3):
                tot[k][i] += r[k][i]
        eff = [eff[0] + r["effects"][0], eff[1] + r["effects"][1]]
        srv = [srv[0] + r["servers"][0], srv[1] + r["servers"][1]]
    agent_recall = tot["agents"][0] / max(1, tot["agents"][1])
    agent_precision = tot["agents"][0] / max(1, tot["agents"][0] + tot["agents"][2])
    tool_recall = tot["tools"][0] / max(1, tot["tools"][1])
    tool_precision = tot["tools"][0] / max(1, tot["tools"][0] + tot["tools"][2])
    effect_acc = eff[0] / max(1, eff[1])
    server_recall = srv[0] / max(1, srv[1])
    with capsys.disabled():
        print(f"\n{'case':26} agents  tools   effects servers")
        for r in rows:
            print(f"{r['case']:26} {r['agents'][0]}/{r['agents'][1]}+{r['agents'][2]:<3} {r['tools'][0]}/{r['tools'][1]}+{r['tools'][2]:<3} "
                  f"{r['effects'][0]}/{r['effects'][1]:<5} {r['servers'][0]}/{r['servers'][1]}")
            for k in ("missing_agents", "extra_agents", "missing_tools", "extra_tools", "wrong_effects"):
                if r[k]:
                    print(f"    {k}: {r[k]}")
        print(f"agents recall {agent_recall:.0%} precision {agent_precision:.0%} · tools recall {tool_recall:.0%} "
              f"precision {tool_precision:.0%} · effects {effect_acc:.0%} · MCP servers {server_recall:.0%}")
    assert agent_recall >= 0.95
    assert tool_recall >= 0.90
    assert agent_precision >= 0.90 and tool_precision >= 0.90
    assert effect_acc >= 0.85
    assert server_recall >= 0.95
