"""Detectors for configuration and content files: MCP configs, CrewAI YAML, skills, prompts, env templates, how the
app is started (Dockerfile, compose, Procfile, pyproject, package.json), SQL/Prisma schemas and eval datasets."""

from __future__ import annotations

import json
import re
import tomllib
from typing import Any, Callable

import yaml

from .scan import Inventory, SourceFile, redact
from .schema import Evidence, Fact


def _ev(sf: SourceFile, line: int = 1) -> list[Evidence]:
    return [Evidence(file=sf.rel, line=line, snippet=sf.snippet(line))]


def _line_of(text: str, needle: str) -> int:
    i = text.find(needle)
    return text.count("\n", 0, i) + 1 if i >= 0 else 1


def _frontmatter(text: str) -> dict[str, Any]:
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def detect_configs(inv: Inventory, add: Callable[[Fact], str]) -> None:
    _mcp_configs(inv, add)
    _crewai_yaml(inv, add)
    _skills(inv, add)
    _prompts(inv, add)
    _env_templates(inv, add)
    _start_commands(inv, add)
    _schemas(inv, add)
    _evals(inv, add)


def _mcp_configs(inv: Inventory, add: Callable[[Fact], str]) -> None:
    for sf in inv.named("mcp.json", ".mcp.json", "**/mcp.json", "**/.mcp.json", "**/claude_desktop_config.json",
                        ".vscode/mcp.json", ".cursor/mcp.json", "**/mcp_config.json", "**/mcp-servers.json"):
        try:
            data = json.loads(sf.text)
        except json.JSONDecodeError:
            continue
        servers = data.get("mcpServers") or data.get("servers") or {}
        if not isinstance(servers, dict):
            continue
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            cmd = spec.get("command")
            args = [str(a) for a in spec.get("args") or []]
            add(Fact(kind="mcp_client", name=name, framework="mcp-config", evidence=_ev(sf, _line_of(sf.text, f'"{name}"')),
                     attrs={"name": name, "file": sf.rel, "command": " ".join([cmd, *args]) if cmd else None,
                            "url": spec.get("url"), "transport": spec.get("type") or ("http" if spec.get("url") else "stdio"),
                            "env_keys": sorted((spec.get("env") or {}).keys()), "config": True}))


def _crewai_yaml(inv: Inventory, add: Callable[[Fact], str]) -> None:
    for sf in inv.named("**/config/agents.yaml", "**/config/agents.yml"):
        try:
            data = yaml.safe_load(sf.text) or {}
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        for key, spec in data.items():
            if isinstance(spec, dict) and ("role" in spec or "goal" in spec):
                desc = " — ".join(str(spec[k]).strip() for k in ("role", "goal") if spec.get(k))
                add(Fact(kind="agent", name=key, framework="crewai", evidence=_ev(sf, _line_of(sf.text, f"{key}:")),
                         attrs={"file": sf.rel, "role": "agent", "config_key": key, "description": redact(desc)[:300],
                                "tools": [], "model": {"value": spec["llm"]} if isinstance(spec.get("llm"), str) else {},
                                "prompt": {"text": redact(str(spec.get("backstory", "")))[:400]} if spec.get("backstory") else {},
                                "confidence": "high", "yaml": True}))


def _skills(inv: Inventory, add: Callable[[Fact], str]) -> None:
    for sf in inv.named("**/SKILL.md", ".claude/agents/*.md", "**/.claude/agents/*.md"):
        fm = _frontmatter(sf.text)
        name = str(fm.get("name") or sf.path.parent.name if sf.path.name == "SKILL.md" else fm.get("name") or sf.path.stem)
        add(Fact(kind="skill", name=name, framework="claude-skill" if sf.path.name == "SKILL.md" else "claude-subagent",
                 evidence=_ev(sf), attrs={"file": sf.rel, "description": redact(str(fm.get("description", "")))[:300],
                                          "tools": fm.get("tools") or fm.get("allowed-tools") or []}))


def _prompts(inv: Inventory, add: Callable[[Fact], str]) -> None:
    for sf in inv.named("**/prompts/**/*.md", "**/prompts/**/*.txt", "**/prompts/**/*.j2", "**/prompts/**/*.jinja*",
                        "**/*.prompt", "**/*.prompty", "**/prompts/**/*.yaml", "**/prompts/**/*.yml"):
        if sf.path.stat().st_size > 60_000:
            continue
        add(Fact(kind="prompt", name=sf.path.stem, framework="file", evidence=_ev(sf),
                 attrs={"file": sf.rel, "text": redact(sf.text)[:400]}))


def _env_templates(inv: Inventory, add: Callable[[Fact], str]) -> None:
    for sf in inv.named(".env.example", ".env.sample", ".env.template", ".env.dist", "**/.env.example", "**/.env.sample"):
        for i, line in enumerate(sf.text.splitlines(), 1):
            m = re.match(r"\s*(?:export\s+)?([A-Z][A-Z0-9_]{1,60})\s*=", line)
            if m:
                add(Fact(kind="env_var", name=m.group(1), framework="env-template",
                         evidence=[Evidence(file=sf.rel, line=i, snippet=redact(line)[:200])], attrs={"file": sf.rel}))


def _start_commands(inv: Inventory, add: Callable[[Fact], str]) -> None:
    for sf in inv.named("**/Dockerfile", "Dockerfile"):
        for i, line in enumerate(sf.text.splitlines(), 1):
            m = re.match(r"\s*(CMD|ENTRYPOINT)\s+(.+)$", line)
            if m:
                raw = m.group(2).strip()
                try:
                    cmd = " ".join(json.loads(raw)) if raw.startswith("[") else raw
                except json.JSONDecodeError:
                    cmd = raw
                add(Fact(kind="entrypoint", name=cmd[:120], framework="docker", evidence=[Evidence(file=sf.rel, line=i, snippet=line)],
                         attrs={"kind": "cli" if not re.search(r"uvicorn|gunicorn|hypercorn|node|next start|serve", cmd) else "http",
                                "command": cmd, "file": sf.rel, "names_used": []}))
    for sf in inv.named("Procfile", "**/Procfile"):
        for i, line in enumerate(sf.text.splitlines(), 1):
            m = re.match(r"(\w+)\s*:\s*(.+)$", line)
            if m:
                add(Fact(kind="entrypoint", name=m.group(2)[:120], framework="procfile", evidence=[Evidence(file=sf.rel, line=i, snippet=line)],
                         attrs={"kind": "http" if m.group(1) == "web" else "cli", "command": m.group(2), "file": sf.rel, "names_used": []}))
    for sf in inv.named("pyproject.toml", "**/pyproject.toml"):
        try:
            data = tomllib.loads(sf.text)
        except tomllib.TOMLDecodeError:
            continue
        for name, target in ((data.get("project") or {}).get("scripts") or {}).items():
            add(Fact(kind="entrypoint", name=name, framework="pyproject", evidence=_ev(sf, _line_of(sf.text, name)),
                     attrs={"kind": "cli", "command": name, "target": target, "file": sf.rel, "names_used": [target.split(":")[-1]]}))
    for sf in inv.named("package.json", "**/package.json"):
        try:
            data = json.loads(sf.text)
        except json.JSONDecodeError:
            continue
        scripts = data.get("scripts") or {}
        for key in ("start", "dev", "serve"):
            if key in scripts:
                add(Fact(kind="entrypoint", name=f"npm run {key}", framework="package.json", evidence=_ev(sf, _line_of(sf.text, f'"{key}"')),
                         attrs={"kind": "http" if re.search(r"next|express|node|tsx|hono|fastify|vite", scripts[key]) else "cli",
                                "command": f"npm run {key}", "script": scripts[key], "file": sf.rel, "names_used": []}))
        if isinstance(data.get("bin"), (str, dict)):
            add(Fact(kind="entrypoint", name=str(data.get("name", "bin")), framework="package.json", evidence=_ev(sf),
                     attrs={"kind": "cli", "command": str(data.get("name", "")), "file": sf.rel, "names_used": []}))


def _schemas(inv: Inventory, add: Callable[[Fact], str]) -> None:
    for sf in inv.named("**/*.sql"):
        for m in re.finditer(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[\"`]?(\w+)[\"`]?\s*\((.*?)\)\s*;", sf.text, re.I | re.S):
            cols: dict[str, str] = {}
            for part in re.split(r",\s*(?![^()]*\))", m.group(2)):
                cm = re.match(r"\s*[\"`]?(\w+)[\"`]?\s+(\w+)", part)
                if cm and cm.group(1).upper() not in ("PRIMARY", "FOREIGN", "UNIQUE", "CONSTRAINT", "CHECK", "KEY", "INDEX"):
                    cols[cm.group(1)] = cm.group(2).upper()
            add(Fact(kind="datastore", name="sql", framework="sql", evidence=_ev(sf, sf.text.count("\n", 0, m.start()) + 1),
                     attrs={"kind": "unknown", "table": m.group(1), "columns": cols, "schema_file": sf.rel}))
    for sf in inv.named("**/schema.prisma"):
        provider = re.search(r'provider\s*=\s*"(postgresql|sqlite|mysql|mongodb)"', sf.text)
        for m in re.finditer(r"model\s+(\w+)\s*\{(.*?)\}", sf.text, re.S):
            cols = {}
            for line in m.group(2).splitlines():
                cm = re.match(r"\s*(\w+)\s+(\w+)", line)
                if cm and not cm.group(1).startswith("@"):
                    cols[cm.group(1)] = {"Int": "INTEGER", "Float": "REAL", "Decimal": "REAL", "Boolean": "BOOLEAN",
                                         "DateTime": "TIMESTAMP", "Json": "JSON"}.get(cm.group(2), "TEXT")
            add(Fact(kind="datastore", name="prisma", framework="prisma", evidence=_ev(sf, sf.text.count("\n", 0, m.start()) + 1),
                     attrs={"kind": {"postgresql": "postgres"}.get(provider.group(1), provider.group(1)) if provider else "unknown",
                            "table": m.group(1).lower(), "columns": cols, "schema_file": sf.rel,
                            "url_env": (re.search(r'env\("(\w+)"\)', sf.text) or [None, None])[1]}))
    for sf in inv.named("**/alembic.ini", "**/migrations/env.py"):
        add(Fact(kind="datastore", name="migrations", framework="alembic", evidence=_ev(sf), attrs={"kind": "unknown", "schema_file": sf.rel}))


def _evals(inv: Inventory, add: Callable[[Fact], str]) -> None:
    keys = ("input", "question", "prompt", "query", "user_input", "message", "task")
    files = inv.named("**/eval*/**/*.jsonl", "**/eval*/**/*.json", "**/eval*/**/*.yaml", "**/eval*/**/*.yml",
                      "**/tests/**/*.jsonl", "**/datasets/**/*.jsonl", "**/golden*/**/*.jsonl", "**/*eval*.jsonl")
    n = 0
    for sf in files:
        rows: list[Any] = []
        try:
            if sf.rel.endswith(".jsonl"):
                rows = [json.loads(line) for line in sf.text.splitlines()[:200] if line.strip()]
            elif sf.rel.endswith(".json"):
                data = json.loads(sf.text)
                rows = data if isinstance(data, list) else data.get("examples") or data.get("cases") or []
            else:
                data = yaml.safe_load(sf.text)
                rows = data if isinstance(data, list) else (data or {}).get("cases") or (data or {}).get("examples") or []
        except (json.JSONDecodeError, yaml.YAMLError, AttributeError):
            continue
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            text = next((row[k] for k in keys if isinstance(row.get(k), str)), None)
            if not text:
                continue
            expected = next((row[k] for k in ("expected", "expected_output", "answer", "output", "ideal", "reference")
                             if isinstance(row.get(k), str)), None)
            add(Fact(kind="test_case", name=text[:60], framework="eval", evidence=_ev(sf, i + 1 if sf.rel.endswith(".jsonl") else 1),
                     attrs={"file": sf.rel, "input": redact(text)[:500], "expected": redact(expected)[:300] if expected else None}))
            n += 1
            if n >= 60:
                return
