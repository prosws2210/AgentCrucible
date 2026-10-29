"""Runs scenarios: builds a sandbox per episode, drives the conversation, grades, saves."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx
import uvicorn

from .calibration import load_statuses
from .checks import CheckResult, GradeContext, grade
from .config import AgentSpec, ProjectConfig, Scenario
from .gateway import EpisodeRoutes, Gateway, McpProxy, split_command
from .stats import summarize_run
from .trajectory import Recorder

DONE = "[DONE]"

SIM_PROMPT = """You are role-playing a CUSTOMER chatting with an online shop's support agent.
Your persona and goal: {persona}

Write ONLY the customer's next message: short, natural, in character.
Do not invent order ids or emails beyond what your persona says.
If your goal is achieved, or the agent clearly cannot help further, reply with exactly {done}"""


@dataclass
class EpisodeResult:
    episode_id: str
    scenario_id: str
    attempt: int
    passed: bool
    checks: list[CheckResult]
    totals: dict[str, Any]
    error: str | None = None
    trajectory: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "episode_id": self.episode_id, "scenario_id": self.scenario_id, "attempt": self.attempt,
            "passed": self.passed, "error": self.error, "totals": self.totals, "trajectory": self.trajectory,
            "checks": [c.to_dict() for c in self.checks],
        }


@dataclass
class RunOptions:
    label: str = ""
    parallel: int = 2
    model: str | None = None
    agent_env: dict[str, str] = field(default_factory=dict)
    out_root: Path | None = None
    cache: str | None = None
    shard: tuple[int, int] | None = None  # (index, total): run only every total-th episode
    run_id: str | None = None


def git_info(root: Path) -> dict[str, str]:
    def g(*args: str) -> str:
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=5).stdout.strip()
        except Exception:
            return ""
    return {"sha": g("rev-parse", "--short", "HEAD"), "branch": g("rev-parse", "--abbrev-ref", "HEAD")}


def with_database(url: str, name: str) -> str:
    """Same Postgres server and credentials, different database."""
    from urllib.parse import urlsplit, urlunsplit
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/" + name, parts.query, parts.fragment))


def git(cwd: Path, *args: str) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args[:2])} failed: {r.stderr.strip()[:300]}")
    return r.stdout


def agent_extra_env(sc: Scenario, dbs: dict[str, Path | str], mcp_servers: set[str]) -> dict[str, str]:
    """What the agent process itself needs from the scenario's environment.

    * fixtures not tied to an MCP server are the agent's own databases: CRUCIBLE_DB_<NAME> (SQLite path) or
      CRUCIBLE_DB_<NAME>_URL (Postgres), which a generated adapter maps onto the app's own setting
    * mocked and denied tools, so adapters can apply them to tools that run inside the agent's process
    """
    env: dict[str, str] = {}
    for name, db in dbs.items():
        if name in mcp_servers:
            continue
        key = "CRUCIBLE_DB_" + re.sub(r"\W", "_", name).upper()
        env[key if isinstance(db, Path) else key + "_URL"] = str(db)
    if sc.environment.mocks:
        env["CRUCIBLE_TOOL_MOCKS"] = json.dumps(sc.environment.mocks)
    if sc.environment.deny_tools:
        env["CRUCIBLE_DENY_TOOLS"] = json.dumps(sc.environment.deny_tools)
    if sc.environment.inject:
        env["CRUCIBLE_TOOL_INJECT"] = json.dumps(sc.environment.inject)
    return env


def rmtree(path: Path) -> None:
    """Delete a temp dir, including read-only files (git objects on Windows)."""
    def _force(func: Any, p: str, _exc: Any) -> None:
        with contextlib.suppress(Exception):
            os.chmod(p, stat.S_IWRITE)
            func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force)
    else:  # pragma: no cover
        shutil.rmtree(path, onerror=_force)


class Runner:
    def __init__(self, cfg: ProjectConfig, opts: RunOptions, on_episode: Callable[[EpisodeResult], None] | None = None):
        self.cfg, self.opts, self.on_episode = cfg, opts, on_episode
        if opts.cache:
            cfg.llm.cache = opts.cache  # type: ignore[assignment]
        self.model = opts.model or cfg.model
        self.out_root = opts.out_root or (cfg.root / ".crucible")
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        self.run_id = opts.run_id or f"run_{stamp}_{uuid.uuid4().hex[:4]}"
        if opts.shard:
            self.run_id += f"-shard{opts.shard[0]}of{opts.shard[1]}"
        self.run_dir = self.out_root / "runs" / self.run_id
        self.gateway = Gateway(cfg.llm, self.out_root / "cache" / "llm", force_model=self.model)
        self.http = httpx.AsyncClient(timeout=300)
        self.judge_status = load_statuses(cfg.root)

    async def run(self, scenarios: list[tuple[Scenario, int]], suite: str | None = None) -> dict[str, Any]:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        server = uvicorn.Server(uvicorn.Config(self.gateway, host="127.0.0.1", port=self.gateway.port,
                                               lifespan="on", access_log=False,
                                               # don't reconfigure the host process's logging (e.g. `crucible serve`)
                                               log_config=None, log_level=None))
        server.capture_signals = contextlib.nullcontext  # type: ignore[method-assign]
        server_task = asyncio.create_task(server.serve())
        while not server.started:
            await asyncio.sleep(0.05)

        started = dt.datetime.now(dt.timezone.utc)
        sem = asyncio.Semaphore(max(1, self.opts.parallel))
        jobs = [(sc, a) for sc, runs in scenarios for a in range(1, runs + 1)]
        if self.opts.shard:
            i, n = self.opts.shard
            jobs = jobs[i::n]

        async def guarded(sc: Scenario, attempt: int) -> EpisodeResult:
            async with sem:
                res = await self.run_episode(sc, attempt)
            if self.on_episode:
                self.on_episode(res)
            return res

        services: list[asyncio.subprocess.Process] = []
        try:
            services = await self._start_services()
            results = await asyncio.gather(*(guarded(sc, a) for sc, a in jobs))
        finally:
            for proc in services:
                await self._stop_service(proc)
            for log in getattr(self, "_service_logs", []):
                log.close()
            server.should_exit = True
            await server_task
            await self.http.aclose()
            await self.gateway.client.aclose()

        run = {
            "run_id": self.run_id,
            "project": self.cfg.project,
            "label": self.opts.label,
            "suite": suite,
            "created_at": started.isoformat(),
            "duration_s": round((dt.datetime.now(dt.timezone.utc) - started).total_seconds(), 1),
            "git": git_info(self.cfg.root),
            "model": self.model,
            "agent_env": self.opts.agent_env,
            "transport": self.cfg.agent.transport,
            "shard": list(self.opts.shard) if self.opts.shard else None,
            "scenarios": [
                {"id": sc.id, "description": sc.description, "tags": sc.tags, "runs": runs,
                 "checks": [c.label for c in sc.checks]}
                for sc, runs in scenarios
            ],
            "episodes": [r.to_dict() for r in results],
        }
        run["summary"] = summarize_run(run)
        (self.run_dir / "run.json").write_text(json.dumps(run, indent=2), encoding="utf-8")
        return run

    # ------------------------------------------------------------ http agent service

    async def _start_services(self) -> list[asyncio.subprocess.Process]:
        """Start every http agent that has a `command` once per run (each named agent may be its own service)."""
        procs: list[asyncio.subprocess.Process] = []
        specs = {id(a): (name, a) for name, a in [("agent", self.cfg.agent), *self.cfg.agents.items()] if a}
        try:
            for name, agent in specs.values():
                proc = await self._start_service(name, agent)
                if proc is not None:
                    procs.append(proc)
        except Exception:
            for proc in procs:
                await self._stop_service(proc)
            raise
        return procs

    async def _start_service(self, name: str, agent: AgentSpec) -> asyncio.subprocess.Process | None:
        """For an http agent with a `command`: start the service and wait until it answers."""
        if agent.transport != "http":
            return None
        if not agent.command:
            await self._wait_ready(agent.url or "", agent.ready_timeout_s, None, name)
            return None
        log_dir = self.run_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_name = "agent-service.log" if name == "agent" else f"agent-service-{name}.log"
        log = open(log_dir / log_name, "w", encoding="utf-8")
        self._service_logs = [*getattr(self, "_service_logs", []), log]
        env = {**os.environ, **agent.env, **self.opts.agent_env, "CRUCIBLE_MODEL": self.model,
               "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8"}
        cwd = str((self.cfg.root / agent.cwd).resolve()) if agent.cwd else str(self.cfg.root)
        proc = await asyncio.create_subprocess_exec(*split_command(agent.command or ""), cwd=cwd, env=env,
                                                    stdout=log, stderr=log)
        try:
            await self._wait_ready(agent.url or "", agent.ready_timeout_s, proc, log_name)
        except Exception:
            await self._stop_service(proc)
            raise
        return proc

    async def _wait_ready(self, url: str, timeout: float, proc: asyncio.subprocess.Process | None,
                          log_name: str = "agent-service.log") -> None:
        deadline = time.monotonic() + timeout
        while True:
            if proc is not None and proc.returncode is not None:
                raise RuntimeError(f"agent service exited with code {proc.returncode}; see logs/{log_name}")
            try:
                await self.http.get(url, timeout=2)  # any HTTP response means it is listening
                return
            except httpx.TransportError:
                pass
            if time.monotonic() > deadline:
                raise RuntimeError(f"agent service at {url} not reachable after {timeout:.0f}s")
            await asyncio.sleep(0.3)

    async def _stop_service(self, proc: asyncio.subprocess.Process | None) -> None:
        if proc is not None and proc.returncode is None:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), 5)
            except TimeoutError:
                proc.kill()
                await proc.wait()

    # ------------------------------------------------------------ one episode

    async def run_episode(self, sc: Scenario, attempt: int) -> EpisodeResult:
        eid = f"{sc.id}--{attempt}--{uuid.uuid4().hex[:6]}"
        rec = Recorder(eid, sc.id, attempt)
        tmp = Path(tempfile.mkdtemp(prefix="crucible-"))
        pg_created: list[str] = []
        error: str | None = None
        checks: list[CheckResult] = []
        rec.add("episode_start", scenario=sc.id, attempt=attempt, model=self.model)
        try:
            dbs = await asyncio.to_thread(self._build_fixtures, sc, tmp, pg_created)
            workspace = await asyncio.to_thread(self._build_workspace, sc, tmp)
            base = self.gateway.base(eid)
            shared_env = {
                **({"CRUCIBLE_WORKSPACE": str(workspace)} if workspace else {}),
                **{f"CRUCIBLE_HTTP_{n.upper()}_URL": f"{base}/http/{n}" for n in sc.environment.http_mocks},
            }
            async with AsyncExitStack() as stack:
                routes = EpisodeRoutes(rec, http_mocks=sc.environment.http_mocks)
                for name, spec in self.cfg.mcp_servers.items():
                    env = dict(shared_env)
                    if name in dbs:  # SQLite path or Postgres URL for this server's fresh database
                        env["CRUCIBLE_DB" if isinstance(dbs[name], Path) else "CRUCIBLE_DB_URL"] = str(dbs[name])
                    proxy = McpProxy(name, spec, env, rec, sc.environment, self.cfg.root)
                    routes.proxies[name] = await stack.enter_async_context(proxy)
                self.gateway.episodes[eid] = routes
                stack.callback(self.gateway.episodes.pop, eid, None)
                try:
                    await self._converse(sc, rec, eid, workspace, stack, dbs)
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
                    rec.add("error", message=error)
            rec.add("episode_end", reason="error" if error else "done", turns=rec.turn)
            checks = await grade(sc, rec, GradeContext(dbs=dbs, judge=self.cfg.judge, http=self.http,
                                                       judge_status=self.judge_status, workspace=workspace))
        except Exception as e:  # infrastructure failure (fixture, MCP server failed to start, ...)
            error = error or f"setup: {type(e).__name__}: {e}"
            rec.add("error", message=error)
        finally:
            rmtree(tmp)
            if pg_created:
                await asyncio.to_thread(self._drop_postgres, pg_created)

        traj = f"episodes/{eid}.jsonl"
        rec.save(self.run_dir / traj)
        passed = error is None and all(c.passed for c in checks if c.hard)
        return EpisodeResult(eid, sc.id, attempt, passed, checks, rec.totals(), error, traj)

    def _resolve(self, sc: Scenario, rel: str) -> Path:
        p = Path(rel)
        if p.is_absolute():
            return p
        if sc.source and (sc.source.parent / rel).exists():
            return sc.source.parent / rel
        return self.cfg.resolve(rel)  # type: ignore[return-value]

    def _build_fixtures(self, sc: Scenario, tmp: Path, pg_created: list[str]) -> dict[str, Path | str]:
        """SQLite file or fresh Postgres database per MCP server, seeded from SQL."""
        dbs: dict[str, Path | str] = {}
        for server, fx in sc.environment.fixtures.items():
            sql = self._resolve(sc, fx.seed).read_text(encoding="utf-8")
            if fx.kind == "postgres":
                dbs[server] = self._create_postgres(sql, pg_created)
                continue
            db = tmp / f"{server}.db"
            conn = sqlite3.connect(db)
            conn.executescript(sql)
            conn.commit()
            conn.close()
            dbs[server] = db
        return dbs

    def _create_postgres(self, sql: str, pg_created: list[str]) -> str:
        import psycopg
        admin = self.cfg.postgres.admin_url
        if not admin:
            raise RuntimeError("postgres fixtures need `postgres.admin_url` in crucible.yaml or CRUCIBLE_POSTGRES_URL")
        name = f"crucible_{uuid.uuid4().hex[:12]}"
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE "{name}"')
        pg_created.append(name)
        url = with_database(admin, name)
        with psycopg.connect(url, autocommit=True) as conn:
            conn.execute(sql)
        return url

    def _drop_postgres(self, names: list[str]) -> None:
        import psycopg
        with contextlib.suppress(Exception), psycopg.connect(self.cfg.postgres.admin_url or "", autocommit=True) as conn:
            for name in names:
                conn.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')

    def _build_workspace(self, sc: Scenario, tmp: Path) -> Path | None:
        """Fresh copy of the scenario's repo with a baseline commit, so graders can diff against it."""
        ws = sc.environment.workspace
        if ws is None:
            return None
        src = self._resolve(sc, ws.path)
        if not src.is_dir():
            raise FileNotFoundError(f"workspace {ws.path!r} not found")
        dst = tmp / "workspace"
        if (src / ".git").exists():
            git(tmp, "clone", "--quiet", "--no-hardlinks", str(src), str(dst))
            if ws.ref:
                git(dst, "checkout", "--quiet", ws.ref)
            git(dst, "config", "core.autocrlf", "false")
        else:
            if ws.ref:
                raise ValueError("workspace.ref needs `path` to be a git repository")
            shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".crucible", "__pycache__", ".pytest_cache"))
            git(dst, "init", "--quiet")
            git(dst, "config", "core.autocrlf", "false")
            git(dst, "add", "-A")
            git(dst, "-c", "user.name=crucible", "-c", "user.email=crucible@localhost",
                "commit", "--quiet", "--allow-empty", "-m", "crucible baseline")
        return dst

    # ------------------------------------------------------------ conversation

    async def _converse(self, sc: Scenario, rec: Recorder, eid: str, workspace: Path | None,
                        stack: AsyncExitStack, dbs: dict[str, Path | str] | None = None) -> None:
        base = self.gateway.base(eid)
        mcp_urls = {n: f"{base}/mcp/{n}" for n in self.cfg.mcp_servers}
        http_urls = {n: f"{base}/http/{n}" for n in sc.environment.http_mocks}
        agent = self.cfg.agent_for(sc.agent)
        extra = agent_extra_env(sc, dbs or {}, set(self.cfg.mcp_servers))
        if agent.transport == "http":
            send = self._http_turns(agent, eid, base, mcp_urls, http_urls, workspace, extra)
        else:
            send = await self._stdio_turns(agent, eid, base, mcp_urls, http_urls, workspace, stack, extra)

        async def say(text: str) -> str:
            rec.turn += 1
            rec.add("user_message", content=text)
            reply = await send(text)
            rec.add("assistant_message", content=reply)
            return reply

        reply = await say(sc.task)
        if sc.user is None:
            return
        history = [("user", sc.task), ("agent", reply)]
        for _ in range(sc.user.max_turns - 1):
            nxt = await self._simulate_user(sc.user.persona, history)
            if nxt is None:
                break
            reply = await say(nxt)
            history += [("user", nxt), ("agent", reply)]

    async def _stdio_turns(self, agent: AgentSpec, eid: str, base: str, mcp_urls: dict[str, str],
                           http_urls: dict[str, str], workspace: Path | None, stack: AsyncExitStack,
                           extra: dict[str, str]) -> Callable[[str], Awaitable[str]]:
        """One agent process per episode; gateway URLs arrive as environment variables."""
        env = {
            **os.environ, **agent.env, **self.opts.agent_env, **extra,
            "OPENAI_BASE_URL": f"{base}/v1", "OPENAI_API_KEY": "agentcrucible",
            "ANTHROPIC_BASE_URL": base, "ANTHROPIC_API_KEY": "agentcrucible",
            "CRUCIBLE_MODEL": self.model, "CRUCIBLE_EPISODE_ID": eid, "CRUCIBLE_EVENTS_URL": f"{base}/events",
            "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
            **({"CRUCIBLE_WORKSPACE": str(workspace)} if workspace else {}),
            **{f"CRUCIBLE_HTTP_{n.upper()}_URL": url for n, url in http_urls.items()},
            **{f"CRUCIBLE_MCP_{n.upper()}_URL": url for n, url in mcp_urls.items()},
        }
        log_path = self.run_dir / "logs" / f"{eid}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = stack.enter_context(open(log_path, "w", encoding="utf-8"))
        cwd = str((self.cfg.root / agent.cwd).resolve()) if agent.cwd else str(self.cfg.root)
        proc = await asyncio.create_subprocess_exec(
            *split_command(agent.command or ""), cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=log, limit=2**22,
        )

        async def _stop() -> None:
            if proc.returncode is None:
                with contextlib.suppress(Exception):
                    proc.stdin.write(b'{"type": "end"}\n')  # type: ignore[union-attr]
                    await proc.stdin.drain()  # type: ignore[union-attr]
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()

        stack.push_async_callback(_stop)

        async def send(text: str) -> str:
            proc.stdin.write((json.dumps({"type": "user", "content": text}) + "\n").encode())  # type: ignore[union-attr]
            await proc.stdin.drain()  # type: ignore[union-attr]
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), agent.turn_timeout_s)  # type: ignore[union-attr]
                if not line:
                    raise RuntimeError(f"agent exited (code {proc.returncode}); see logs/{log_path.name}")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # stray print() output from the agent
                if msg.get("type") == "assistant":
                    return str(msg.get("content", ""))

        return send

    def _http_turns(self, agent: AgentSpec, eid: str, base: str, mcp_urls: dict[str, str],
                    http_urls: dict[str, str], workspace: Path | None,
                    extra: dict[str, str]) -> Callable[[str], Awaitable[str]]:
        """A long-running agent service; gateway URLs travel with every request in `context`."""
        history: list[dict[str, str]] = []
        context = {
            "episode_id": eid,
            "openai_base_url": f"{base}/v1",
            "anthropic_base_url": base,
            "api_key": "agentcrucible",
            "model": self.model,
            "mcp": mcp_urls,
            "workspace": str(workspace) if workspace else None,
            "http": http_urls,
            "events_url": f"{base}/events",
            "env": {**self.opts.agent_env, **extra},
        }

        async def send(text: str) -> str:
            history.append({"role": "user", "content": text})
            r = await self.http.post(agent.url or "", json={"episode_id": eid, "messages": history, "context": context},
                                     headers={"X-Crucible-Episode": eid, **agent.headers},
                                     timeout=agent.turn_timeout_s)
            if r.status_code >= 400:
                raise RuntimeError(f"agent returned HTTP {r.status_code}: {r.text[:300]}")
            data = r.json()
            reply = data.get("content") if isinstance(data, dict) else None
            if not isinstance(reply, str):
                raise RuntimeError(f"agent response must be JSON with a string `content`, got {str(data)[:200]}")
            history.append({"role": "assistant", "content": reply})
            return reply

        return send

    async def _simulate_user(self, persona: str, history: list[tuple[str, str]]) -> str | None:
        s = self.cfg.simulator
        # From the simulator's point of view it is the assistant and the agent is the user.
        msgs = [{"role": "system", "content": SIM_PROMPT.format(persona=persona, done=DONE)}]
        msgs += [{"role": "assistant" if who == "user" else "user", "content": text} for who, text in history]
        r = await self.http.post(s.base_url.rstrip("/") + "/chat/completions",
                                 headers={"Authorization": f"Bearer {s.api_key}"},
                                 json={"model": s.model, "messages": msgs, "temperature": s.temperature})
        r.raise_for_status()
        text = (r.json()["choices"][0]["message"]["content"] or "").strip().strip('"')
        if not text or DONE in text:
            return None
        return text
