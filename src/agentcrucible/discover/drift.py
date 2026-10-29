"""`crucible discover --check`: compare a fresh scan with the approved `discovery.json` (plan section 10)."""

from __future__ import annotations

from typing import Any

from .schema import Discovery


def coverage(d: Discovery) -> dict[str, Any]:
    """Which included agents and tools have at least one approved scenario."""
    texts = [s.yaml for s in d.scenarios if s.include]
    agents = [a for a in d.agents if a.include]
    tools = sorted({t for a in agents for t in a.tools})
    tested_tools = [t for t in tools if any(f" {t}" in x or f": {t}\n" in x or f"tool: {t}" in x for x in texts)]
    tested_agents = [a.id for a in agents if any(s.agent == a.id and s.include for s in d.scenarios)]
    return {"agents": len(agents), "agents_tested": len(tested_agents), "tools": len(tools), "tools_tested": len(tested_tools),
            "untested_tools": [t for t in tools if t not in tested_tools]}


def check(approved: Discovery, fresh: Discovery) -> dict[str, Any]:
    old_agents = {a.id: a for a in approved.agents}
    new_agents = {a.id: a for a in fresh.agents}
    old_tools = {t.name: t for t in approved.tools}
    new_tools = {t.name: t for t in fresh.tools}
    cov = coverage(approved)
    tested = set(t for a in approved.agents if a.include for t in a.tools) - set(cov["untested_tools"])
    added_tools = [{"name": n, "effects": t.effects, "agents": t.agents, "tested": n in tested}
                   for n, t in new_tools.items() if n not in old_tools]
    changed = [{"name": n, "before": old_tools[n].effects, "after": t.effects}
               for n, t in new_tools.items() if n in old_tools and set(t.effects) != set(old_tools[n].effects)]
    report = {
        "added_agents": [{"id": a.id, "name": a.name, "framework": a.framework} for i, a in new_agents.items() if i not in old_agents],
        "removed_agents": [i for i in old_agents if i not in new_agents],
        "added_tools": added_tools,
        "removed_tools": [n for n in old_tools if n not in new_tools],
        "changed_effects": changed,
        "stale_scenarios": [s.id for s in approved.scenarios if s.include and s.agent not in new_agents],
        "coverage": cov,
    }
    risky = [t for t in added_tools if "destructive" in t["effects"] and not t["tested"]]
    report["fail"] = bool(report["added_agents"] or risky or [c for c in changed if "destructive" in c["after"]])
    report["markdown"] = to_markdown(report)
    return report


def to_markdown(r: dict[str, Any]) -> str:
    lines = ["## AgentCrucible · agent map drift", ""]
    if not any(r[k] for k in ("added_agents", "removed_agents", "added_tools", "removed_tools", "changed_effects")):
        lines.append("No changes to agents or tools since the approved map.")
    for a in r["added_agents"]:
        lines.append(f"- **New agent** `{a['name']}` ({a['framework']}) has no tests yet.")
    for i in r["removed_agents"]:
        lines.append(f"- Agent `{i}` was removed; its scenarios are stale.")
    for t in r["added_tools"]:
        badge = f" ({', '.join(t['effects'])})" if t["effects"] else ""
        lines.append(f"- **New tool** `{t['name']}`{badge}" + ("" if t["tested"] else " has no tests."))
    for t in r["removed_tools"]:
        lines.append(f"- Tool `{t}` was removed.")
    for c in r["changed_effects"]:
        lines.append(f"- Tool `{c['name']}` changed: {', '.join(c['before']) or 'unknown'} → {', '.join(c['after']) or 'unknown'}.")
    cov = r["coverage"]
    lines += ["", f"Coverage: {cov['agents_tested']}/{cov['agents']} agents and {cov['tools_tested']}/{cov['tools']} tools have scenarios."]
    if r["fail"]:
        lines += ["", "Run `crucible discover . --update` to review drafts for the new parts."]
    return "\n".join(lines)
