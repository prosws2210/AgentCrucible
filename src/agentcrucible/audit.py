"""`crucible mcp-audit`: test any MCP server and produce a graded report card.

Suites
    conformance    handshake, tool listing, schema validity, unknown-tool handling, liveness
    tool_quality   descriptions, parameter docs, overlapping tools, tool-list size, destructive hints
    robustness     schema-driven fuzzing: wrong types, missing args, huge/empty/odd values
    security       SQL-injection differential, path traversal, SSRF, internal details leaked in errors
    behavioral     (optional, needs an LLM) can a model pick the right tool for a natural request?
    performance    latency of a read-only tool under concurrency
"""

from __future__ import annotations

import asyncio
import itertools
import json
import os
import re
import sqlite3
import tempfile
import time
from contextlib import AsyncExitStack
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import jsonschema
import mcp.types as mt
import numpy as np
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

from .gateway import content_text, split_command

SEVERITY_PENALTY = {"critical": 40, "high": 25, "medium": 10, "low": 3, "info": 0}
SUITES = ["conformance", "tool_quality", "robustness", "security", "behavioral", "performance"]
WEIGHTS = {"conformance": 1.0, "tool_quality": 1.0, "robustness": 1.0, "security": 1.5, "behavioral": 1.0, "performance": 0.5}
INTERNAL_LEAK = re.compile(
    r"Traceback|list index out of range|KeyError|IndexError|NoneType|AttributeError|sqlite3|OperationalError|"
    r"psycopg|SQLSTATE|syntax error|Errno|FileNotFoundError|[A-Z]:\\\\?Users|/home/\w+|/usr/lib/python", re.I)
READ_ONLY = re.compile(r"^(get|list|search|find|read|lookup|fetch|describe|show|query)", re.I)
DESTRUCTIVE = re.compile(r"(delete|remove|cancel|refund|drop|send|pay|transfer|update|create|write|issue)", re.I)
SQLI = "' OR '1'='1"
CANARY_TOKEN = "crucible-canary-" + os.urandom(6).hex()


def traversal_payloads(canary: Path) -> list[str]:
    """Paths that only resolve to our canary file if the server fails to confine paths."""
    rel = canary.as_posix().split(":", 1)[-1].lstrip("/")  # drop drive / root
    return [str(canary), canary.as_posix(), "../" * 16 + rel, "..\\" * 16 + rel.replace("/", "\\")]


@dataclass
class Finding:
    suite: str
    severity: str
    title: str
    detail: str = ""
    tool: str | None = None


@dataclass
class AuditReport:
    target: str
    server_name: str = ""
    protocol_version: str = ""
    tools: list[dict[str, Any]] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)
    scores: dict[str, int] = field(default_factory=dict)
    overall: int = 0
    grade: str = ""
    duration_s: float = 0.0

    def add(self, suite: str, severity: str, title: str, detail: str = "", tool: str | None = None) -> None:
        self.findings.append(Finding(suite, severity, title, detail, tool))

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["findings"] = [asdict(f) for f in self.findings]
        return d


def letter(score: int) -> str:
    return "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"


# ------------------------------------------------------------------ connection


class Target:
    """A connection to the server under audit. Restartable, so a crash doesn't end the audit."""

    def __init__(self, command: str | None, url: str | None, env: dict[str, str], cwd: str | None):
        self.command, self.url, self.env, self.cwd = command, url, env, cwd
        self.stack: AsyncExitStack | None = None
        self.session: ClientSession | None = None
        self.init: mt.InitializeResult | None = None

    async def connect(self) -> None:
        self.stack = AsyncExitStack()
        if self.url:
            read, write, _ = await self.stack.enter_async_context(streamablehttp_client(self.url))
        else:
            cmd = split_command(self.command or "")
            params = StdioServerParameters(command=cmd[0], args=cmd[1:], env={**os.environ, **self.env}, cwd=self.cwd)
            read, write = await self.stack.enter_async_context(stdio_client(params, errlog=open(os.devnull, "w")))
        self.session = await self.stack.enter_async_context(ClientSession(read, write))
        self.init = await asyncio.wait_for(self.session.initialize(), 30)

    async def close(self) -> None:
        if self.stack:
            try:
                await self.stack.aclose()
            except Exception:
                pass
        self.stack, self.session = None, None

    async def restart(self) -> None:
        await self.close()
        await self.connect()

    async def call(self, tool: str, args: dict[str, Any], timeout: float = 15) -> tuple[str, bool, float]:
        """Return (text, is_error, seconds). Raises on transport failure / timeout."""
        assert self.session is not None
        t0 = time.monotonic()
        res = await asyncio.wait_for(self.session.call_tool(tool, args), timeout)
        return content_text(list(res.content)), bool(res.isError), time.monotonic() - t0

    async def alive(self) -> bool:
        try:
            assert self.session is not None
            await asyncio.wait_for(self.session.list_tools(), 10)
            return True
        except Exception:
            return False


# ------------------------------------------------------------------ helpers


def sample_value(schema: dict[str, Any], name: str = "") -> Any:
    t = schema.get("type")
    if "enum" in schema:
        return schema["enum"][0]
    if "default" in schema:
        return schema["default"]
    if t == "integer":
        return 1
    if t == "number":
        return 1.0
    if t == "boolean":
        return True
    if t == "array":
        return []
    if t == "object":
        return {}
    if "email" in name.lower():
        return "test@example.com"
    return "test"


def valid_args(tool: mt.Tool) -> dict[str, Any]:
    props = tool.inputSchema.get("properties", {}) or {}
    req = tool.inputSchema.get("required", []) or []
    return {k: sample_value(props[k], k) for k in req if k in props}


def fuzz_cases(tool: mt.Tool) -> list[tuple[str, dict[str, Any]]]:
    props = tool.inputSchema.get("properties", {}) or {}
    req = tool.inputSchema.get("required", []) or []
    base = valid_args(tool)
    cases: list[tuple[str, dict[str, Any]]] = []
    if req:
        cases.append(("missing required arguments", {}))
    for k, s in props.items():
        t = s.get("type")
        if t in ("integer", "number"):
            cases += [(f"{k}: negative number", {**base, k: -1}), (f"{k}: huge number", {**base, k: 10**12}),
                      (f"{k}: wrong type (string)", {**base, k: "not-a-number"})]
        elif t == "string" or t is None:
            cases += [(f"{k}: empty string", {**base, k: ""}), (f"{k}: 20k chars", {**base, k: "A" * 20000}),
                      (f"{k}: nonexistent value", {**base, k: "zz-does-not-exist-404"}),
                      (f"{k}: unicode/control chars", {**base, k: "ü\u0000‮💥"}),
                      (f"{k}: wrong type (object)", {**base, k: {"x": 1}})]
    return cases


def tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z]{3,}", text.lower())} - {"the", "and", "for", "with", "this", "that", "from", "returns"}


# ------------------------------------------------------------------ suites


async def suite_conformance(t: Target, rep: AuditReport, tools: list[mt.Tool]) -> None:
    init = t.init
    assert init is not None
    rep.server_name = init.serverInfo.name if init.serverInfo else ""
    rep.protocol_version = str(init.protocolVersion)
    if not init.serverInfo or not init.serverInfo.name:
        rep.add("conformance", "low", "serverInfo.name missing")
    if not tools:
        rep.add("conformance", "high", "Server exposes no tools")
    names = [x.name for x in tools]
    for dup in {n for n in names if names.count(n) > 1}:
        rep.add("conformance", "high", "Duplicate tool name", tool=dup)
    for tool in tools:
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", tool.name):
            rep.add("conformance", "medium", "Tool name has characters some clients reject", tool=tool.name)
        try:
            jsonschema.Draft202012Validator.check_schema(tool.inputSchema)
            if tool.inputSchema.get("type") != "object":
                rep.add("conformance", "medium", "inputSchema type must be 'object'", tool=tool.name)
        except jsonschema.SchemaError as e:
            rep.add("conformance", "high", "Invalid inputSchema", str(e.message)[:200], tool=tool.name)
    try:
        _, is_err, _ = await t.call("__agentcrucible_no_such_tool__", {})
        if not is_err:
            rep.add("conformance", "medium", "Unknown tool call did not return an error")
    except mt.McpError:
        pass  # JSON-RPC error is a correct response
    except Exception as e:
        rep.add("conformance", "high", "Unknown tool call broke the connection", str(e)[:200])
        await t.restart()


async def suite_tool_quality(rep: AuditReport, tools: list[mt.Tool]) -> None:
    size = 0
    for tool in tools:
        d = (tool.description or "").strip()
        size += len(json.dumps(tool.model_dump(exclude_none=True)))
        if not d:
            rep.add("tool_quality", "high", "Tool has no description; models must guess what it does", tool=tool.name)
        elif len(d) < 25:
            rep.add("tool_quality", "medium", "Tool description is too short to guide a model", repr(d), tool=tool.name)
        props = tool.inputSchema.get("properties", {}) or {}
        undocumented = [k for k, s in props.items() if not s.get("description")]
        if undocumented:
            rep.add("tool_quality", "low", "Parameters without descriptions", ", ".join(undocumented), tool=tool.name)
        cryptic = [k for k in props if len(k) <= 2]
        if cryptic:
            rep.add("tool_quality", "medium", "Cryptic parameter names", ", ".join(cryptic), tool=tool.name)
        ann = tool.annotations
        if DESTRUCTIVE.search(tool.name) and not (ann and ann.destructiveHint):
            rep.add("tool_quality", "low", "Likely destructive tool without destructiveHint annotation", tool=tool.name)
    for a, b in itertools.combinations(tools, 2):
        ta, tb = tokens(a.name + " " + (a.description or "")), tokens(b.name + " " + (b.description or ""))
        if ta and tb:
            j = len(ta & tb) / len(ta | tb)
            if j >= 0.5:
                rep.add("tool_quality", "medium", "Tools look interchangeable to a model",
                        f"{a.name} vs {b.name} (overlap {j:.2f})", tool=a.name)
    est_tokens = size // 4
    rep.metrics["tool_list_tokens"] = est_tokens
    if est_tokens > 8000:
        rep.add("tool_quality", "medium", "Tool list is large and eats context", f"~{est_tokens} tokens")


async def suite_robustness(t: Target, rep: AuditReport, tools: list[mt.Tool], destructive_ok: bool) -> None:
    n_cases = n_bad = 0
    for tool in tools:
        if DESTRUCTIVE.search(tool.name) and not destructive_ok:
            continue
        seen: set[str] = set()
        for label, args in fuzz_cases(tool):
            n_cases += 1
            try:
                text, is_err, secs = await t.call(tool.name, args)
            except asyncio.TimeoutError:
                n_bad += 1
                rep.add("robustness", "high", "Hangs on fuzzed input (>15s)", label, tool=tool.name)
                await t.restart()
                continue
            except mt.McpError:
                continue  # protocol-level error is an acceptable rejection
            except Exception as e:
                n_bad += 1
                rep.add("robustness", "critical", "Server crashed / connection lost on fuzzed input", f"{label}: {e}"[:200], tool=tool.name)
                await t.restart()
                continue
            if is_err and INTERNAL_LEAK.search(text):
                n_bad += 1
                key = "leak"
                if key not in seen:
                    seen.add(key)
                    rep.add("robustness", "medium", "Unhandled exception on bad input (internal error leaked)",
                            f"{label} → {text[:160]}", tool=tool.name)
    rep.metrics["fuzz_cases"] = n_cases
    rep.metrics["fuzz_failures"] = n_bad
    if not await t.alive():
        rep.add("robustness", "critical", "Server stopped responding after fuzzing")
        await t.restart()


async def suite_security(t: Target, rep: AuditReport, tools: list[mt.Tool], destructive_ok: bool) -> None:
    canary = Path(tempfile.mkdtemp(prefix="crucible-canary-")) / "canary.txt"
    canary.write_text(CANARY_TOKEN, encoding="utf-8")
    for tool in tools:
        if DESTRUCTIVE.search(tool.name) and not destructive_ok:
            continue
        props = tool.inputSchema.get("properties", {}) or {}
        base = valid_args(tool)
        for k, s in props.items():
            if s.get("type") not in ("string", None):
                continue
            # SQL injection: a nonexistent value fails, but the same value with a tautology succeeds
            try:
                miss_text, miss_err, _ = await t.call(tool.name, {**base, k: "zz-does-not-exist-404"})
                inj_text, inj_err, _ = await t.call(tool.name, {**base, k: "zz-does-not-exist-404" + SQLI})
                if inj_err and re.search(r"syntax|sqlite|SQL|unrecognized token|near \"", inj_text, re.I):
                    rep.add("security", "high", "SQL error on quote characters (likely injectable)",
                            f"param {k!r} → {inj_text[:140]}", tool=tool.name)
                elif (miss_err or miss_text.strip() in ("", "[]", "{}", "null")) and not inj_err and inj_text.strip() not in ("", "[]", "{}", "null"):
                    rep.add("security", "critical", "SQL injection: tautology returns data a normal lookup doesn't",
                            f"param {k!r} with {SQLI!r} → {inj_text[:140]}", tool=tool.name)
            except Exception:
                await t.restart()
            # path traversal
            if re.search(r"path|file|doc|name", k, re.I):
                for payload in traversal_payloads(canary):
                    try:
                        text, is_err, _ = await t.call(tool.name, {**base, k: payload})
                    except Exception:
                        await t.restart()
                        continue
                    if CANARY_TOKEN in text:
                        rep.add("security", "critical", "Path traversal: reads arbitrary files outside its root",
                                f"param {k!r} returned a canary file planted outside the server's directory "
                                f"(payload {payload[:70]!r})", tool=tool.name)
                        break
            # SSRF
            if re.search(r"url|uri|endpoint|link|href", k, re.I):
                try:
                    text, is_err, _ = await t.call(tool.name, {**base, k: "http://169.254.169.254/latest/meta-data/"}, timeout=8)
                    if not is_err:
                        rep.add("security", "high", "Fetches internal/metadata URLs (SSRF)", f"param {k!r}", tool=tool.name)
                except Exception:
                    await t.restart()


BEHAVIOR_GEN = """Here is a tool an AI assistant can use:
name: {name}
description: {desc}
parameters: {params}

Write {n} different, realistic requests a user might type that should be handled with exactly this tool.
Do not mention the tool name. Respond with JSON: {{"requests": ["...", "..."]}}"""


async def suite_behavioral(rep: AuditReport, tools: list[mt.Tool], model: str, base_url: str, api_key: str) -> None:
    oa_tools = [{"type": "function", "function": {"name": x.name, "description": x.description or "",
                                                   "parameters": x.inputSchema}} for x in tools]
    total = correct = 0
    confusions: dict[str, dict[str, int]] = {}
    async with httpx.AsyncClient(timeout=300, base_url=base_url.rstrip("/"),
                                 headers={"Authorization": f"Bearer {api_key}"}) as http:
        for tool in tools:
            r = await http.post("/chat/completions", json={
                "model": model, "temperature": 0.7, "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": BEHAVIOR_GEN.format(
                    name=tool.name, desc=tool.description or "(none)",
                    params=json.dumps(tool.inputSchema.get("properties", {})), n=3)}]})
            try:
                reqs = json.loads(r.json()["choices"][0]["message"]["content"])["requests"][:3]
            except Exception:
                continue
            for q in reqs:
                rr = await http.post("/chat/completions", json={
                    "model": model, "temperature": 0, "tools": oa_tools, "tool_choice": "auto",
                    "messages": [{"role": "system", "content": "Use the single most appropriate tool."},
                                 {"role": "user", "content": str(q)}]})
                msg = rr.json()["choices"][0]["message"]
                picked = ((msg.get("tool_calls") or [{}])[0].get("function") or {}).get("name") or "(no tool)"
                total += 1
                if picked == tool.name:
                    correct += 1
                else:
                    confusions.setdefault(tool.name, {}).setdefault(picked, 0)
                    confusions[tool.name][picked] += 1
    acc = correct / total if total else float("nan")
    rep.metrics["behavioral"] = {"model": model, "requests": total, "tool_selection_accuracy": acc, "confusions": confusions}
    for tool, wrong in confusions.items():
        n = sum(wrong.values())
        sev = "high" if n >= 2 else "medium"
        rep.add("behavioral", sev, f"Model picks the wrong tool ({n}/3 requests)",
                ", ".join(f"chose {k} {v}x" for k, v in wrong.items()), tool=tool)


async def suite_performance(t: Target, rep: AuditReport, tools: list[mt.Tool], n: int = 30, conc: int = 5) -> None:
    candidates = [x for x in tools if READ_ONLY.match(x.name)]
    chosen = None
    for tool in candidates:
        try:
            _, is_err, _ = await t.call(tool.name, valid_args(tool))
            if not is_err:
                chosen = tool
                break
        except Exception:
            continue
    if not chosen:
        rep.metrics["performance"] = {"skipped": "no read-only tool succeeded with sample arguments"}
        return
    lat: list[float] = []
    sem = asyncio.Semaphore(conc)

    async def one() -> None:
        async with sem:
            try:
                _, _, s = await t.call(chosen.name, valid_args(chosen))
                lat.append(s * 1000)
            except Exception:
                pass

    await asyncio.gather(*(one() for _ in range(n)))
    if not lat:
        return
    p50, p95 = float(np.percentile(lat, 50)), float(np.percentile(lat, 95))
    rep.metrics["performance"] = {"tool": chosen.name, "calls": len(lat), "concurrency": conc,
                                  "p50_ms": round(p50, 1), "p95_ms": round(p95, 1)}
    if len(lat) < n:
        rep.add("performance", "high", "Calls failed under concurrency", f"{n - len(lat)}/{n} failed", tool=chosen.name)
    if p95 > 2000:
        rep.add("performance", "medium", "Slow under concurrency", f"p95 {p95:.0f} ms", tool=chosen.name)


# ------------------------------------------------------------------ orchestrator


async def run_audit(command: str | None, url: str | None, env: dict[str, str], cwd: str | None,
                    fixture: Path | None, destructive_ok: bool, behavioral_model: str | None,
                    llm_base_url: str, llm_api_key: str) -> AuditReport:
    started = time.monotonic()
    tmp = None
    if fixture:
        tmp = Path(tempfile.mkdtemp(prefix="crucible-audit-"))
        db = tmp / "audit.db"
        conn = sqlite3.connect(db)
        conn.executescript(fixture.read_text(encoding="utf-8"))
        conn.close()
        env = {**env, "CRUCIBLE_DB": str(db)}
    rep = AuditReport(target=url or command or "")
    t = Target(command, url, env, cwd)
    await t.connect()
    try:
        tools = (await t.session.list_tools()).tools  # type: ignore[union-attr]
        rep.tools = [{"name": x.name, "description": x.description or "",
                      "params": list((x.inputSchema.get("properties") or {}).keys())} for x in tools]
        await suite_conformance(t, rep, tools)
        await suite_tool_quality(rep, tools)
        await suite_robustness(t, rep, tools, destructive_ok)
        await suite_security(t, rep, tools, destructive_ok)
        if behavioral_model:
            await suite_behavioral(rep, tools, behavioral_model, llm_base_url, llm_api_key)
        await suite_performance(t, rep, tools)
    finally:
        await t.close()
    ran = [s for s in SUITES if s != "behavioral" or behavioral_model]
    for s in ran:
        rep.scores[s] = max(0, 100 - sum(SEVERITY_PENALTY[f.severity] for f in rep.findings if f.suite == s))
    rep.overall = round(sum(rep.scores[s] * WEIGHTS[s] for s in ran) / sum(WEIGHTS[s] for s in ran))
    # One critical issue makes a server unsafe to ship, whatever the average says.
    if any(f.severity == "critical" for f in rep.findings):
        rep.overall = min(rep.overall, 64)
    elif any(f.severity == "high" for f in rep.findings):
        rep.overall = min(rep.overall, 79)
    rep.grade = letter(rep.overall)
    rep.duration_s = round(time.monotonic() - started, 1)
    return rep


# ------------------------------------------------------------------ outputs


SEV_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
SEV_ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "⬜", "info": "·"}


def audit_markdown(rep: AuditReport) -> str:
    lines = [f"## MCP Audit · {rep.server_name or rep.target}", "",
             f"**Grade {rep.grade} ({rep.overall}/100)** · protocol `{rep.protocol_version}` · {len(rep.tools)} tools · {rep.duration_s}s", "",
             "| Suite | Score | Findings |", "|---|---|---|"]
    for s, score in rep.scores.items():
        n = sum(1 for f in rep.findings if f.suite == s)
        lines.append(f"| {s.replace('_', ' ')} | {score} ({letter(score)}) | {n} |")
    lines += ["", "### Findings", ""]
    for f in sorted(rep.findings, key=lambda f: SEV_ORDER[f.severity]):
        lines.append(f"- {SEV_ICON[f.severity]} **{f.severity}** · {f.suite} · {('`' + f.tool + '` · ') if f.tool else ''}{f.title}"
                     + (f"  \n  <sub>{f.detail}</sub>" if f.detail else ""))
    b = rep.metrics.get("behavioral")
    if b:
        lines += ["", f"Tool-selection accuracy with `{b['model']}`: **{b['tool_selection_accuracy'] * 100:.0f}%** over {b['requests']} generated requests."]
    p = rep.metrics.get("performance", {})
    if "p95_ms" in p:
        lines.append(f"Latency of `{p['tool']}`: p50 {p['p50_ms']} ms · p95 {p['p95_ms']} ms at concurrency {p['concurrency']}.")
    badge_color = {"A": "brightgreen", "B": "green", "C": "yellow", "D": "orange", "F": "red"}[rep.grade]
    lines += ["", f"Badge: `![MCP audit](https://img.shields.io/badge/MCP%20audit-{rep.grade}%20{rep.overall}-{badge_color})`"]
    return "\n".join(lines) + "\n"


def audit_junit(rep: AuditReport) -> str:
    from xml.sax.saxutils import escape, quoteattr
    cases = []
    for s in rep.scores:
        fs = [f for f in rep.findings if f.suite == s and f.severity in ("critical", "high", "medium")]
        if not fs:
            cases.append(f'<testcase classname="mcp-audit.{s}" name="{s}"/>')
        for f in fs:
            cases.append(f'<testcase classname="mcp-audit.{s}" name={quoteattr((f.tool or "") + ": " + f.title)}>'
                         f'<failure message={quoteattr(f.severity)}>{escape(f.detail)}</failure></testcase>')
    failures = sum(1 for c in cases if "<failure" in c)
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n<testsuite name="mcp-audit" tests="{len(cases)}" failures="{failures}">\n'
            + "\n".join(cases) + "\n</testsuite>\n")
