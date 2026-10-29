"""Codebase import: find the agents, tools and MCP servers in a repository and draft their tests (docs/CODEBASE-IMPORT.md)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx

from .apply import apply, reality, smoke_run, validate, write_project
from .drift import check, coverage
from .plan import OUT_DIR, build_plan, project_files
from .schema import Discovery
from .sources import clone, is_git_url
from .synthesize import discover

__all__ = ["OUT_DIR", "Discovery", "apply", "build_plan", "check", "clone", "coverage", "default_llm", "discover",
           "is_git_url", "load", "merge_review", "project_files", "reality", "smoke_run", "validate", "write_project"]


def load(path: Path) -> Discovery:
    return Discovery.model_validate_json(path.read_text(encoding="utf-8"))


def default_llm(url: str | None, model: str | None) -> tuple[str | None, str | None]:
    """The synthesis model: what the user asked for, else the local model server if it answers quickly."""
    url = url or "http://localhost:11434/v1"
    try:
        r = httpx.get(url.rstrip("/") + "/models", timeout=2)
        names = [m.get("id") for m in r.json().get("data", [])] if r.status_code == 200 else []
    except (httpx.HTTPError, ValueError):
        return None, None
    if model:
        return url, model
    for pref in ("qwen2.5:7b", "qwen2.5:3b", "llama3.1:8b", "llama3.2:3b"):
        if pref in names or f"{pref}:latest" in names:
            return url, pref
    return (url, names[0]) if names else (None, None)


def merge_review(fresh: Discovery, approved: Discovery) -> Discovery:
    """Carry the user's review (include toggles, answers, edited names/purposes) onto a fresh scan."""
    old_agents = {a.id: a for a in approved.agents}
    for a in fresh.agents:
        o = old_agents.get(a.id)
        if o:
            a.include, a.name, a.purpose = o.include, o.name, o.purpose or a.purpose
    old_tools = {t.name: t for t in approved.tools}
    for t in fresh.tools:
        o = old_tools.get(t.name)
        if o:
            t.include = o.include
            if o.effects and set(o.effects) >= set(t.effects):  # keep the reviewer's stricter label; a new effect wins
                t.effects = o.effects
    answers = {q.text: q.answer for q in approved.questions if q.answer}
    for q in fresh.questions:
        q.answer = answers.get(q.text, q.answer)
    return fresh


def summary(d: Discovery) -> dict[str, Any]:
    return {"agents": sum(a.include for a in d.agents), "tools": len(d.tools), "mcp_servers": len(d.mcp_servers),
            "questions": len(d.questions), "scenarios": sum(s.include for s in d.scenarios)}
