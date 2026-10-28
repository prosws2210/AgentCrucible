"""Runs scenarios: builds a sandbox per episode, drives the conversation, grades, saves."""

from __future__ import annotations

import asyncio
import contextlib
import datetime as dt
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import uuid
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import httpx
import uvicorn

from .calibration import load_statuses
from .checks import CheckResult, GradeContext, grade
from .config import ProjectConfig, Scenario
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

        try:
            results = await asyncio.gather(*(guarded(sc, a) for sc, a in jobs))
        finally:
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

    # ------------------------------------------------------------ one episode

    async def run_episode(self, sc: Scenario, attempt: int) -> EpisodeResult:
        eid = f"{sc.id}--{attempt}--{uuid.uuid4().hex[:6]}"
        rec = Recorder(eid, sc.id, attempt)
        tmp = Path(tempfile.mkdtemp(prefix="crucible-"))
        error: str | None = None
        checks: list[CheckResult] = []
        rec.add("episode_start", scenario=sc.id, attempt=attempt, model=self.model)
        try:
            dbs = self._build_fixtures(sc, tmp)
            async with AsyncExitStack() as stack:
                routes = EpisodeRoutes(rec)
                for name, spec in self.cfg.mcp_servers.items():
                    env = {"CRUCIBLE_DB": str(dbs[name])} if name in dbs else {}
                    proxy = McpProxy(name, spec, env, rec, sc.environment, self.cfg.root)
                    routes.proxies[name] = await stack.enter_async_context(proxy)
                self.gateway.episodes[eid] = routes
                stack.callback(self.gateway.episodes.pop, eid, None)
                try:
                    await self._converse(sc, rec, eid, tmp, stack)
                except Exception as e:
                    error = f"{type(e).__name__}: {e}"
                    rec.add("error", message=error)
            rec.add("episode_end", reason="error" if error else "done", turns=rec.turn)
            checks = await grade(sc, rec, GradeContext(dbs=dbs, judge=self.cfg.judge, http=self.http,
                                                       judge_status=self.judge_status))
        except Exception as e:  # infrastructure failure (fixture, MCP server failed to start, ...)
            error = error or f"setup: {type(e).__name__}: {e}"
            rec.add("error", message=error)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        traj = f"episodes/{eid}.jsonl"
        rec.save(self.run_dir / traj)
        passed = error is None and all(c.passed for c in checks if c.hard)
        return EpisodeResult(eid, sc.id, attempt, passed, checks, rec.totals(), error, traj)

    def _build_fixtures(self, sc: Scenario, tmp: Path) -> dict[str, Path]:
        dbs: dict[str, Path] = {}
        for server, seed in sc.environment.fixtures.items():
            seed_path = (sc.source.parent / seed) if sc.source and not Path(seed).is_absolute() else Path(seed)
            if not seed_path.exists():
                seed_path = self.cfg.resolve(seed)  # type: ignore[assignment]
            db = tmp / f"{server}.db"
            conn = sqlite3.connect(db)
            conn.executescript(seed_path.read_text(encoding="utf-8"))
            conn.commit()
            conn.close()
            dbs[server] = db
        return dbs

    async def _converse(self, sc: Scenario, rec: Recorder, eid: str, tmp: Path, stack: AsyncExitStack) -> None:
        agent = self.cfg.agent
        base = self.gateway.base(eid)
        env = {
            **os.environ, **agent.env, **self.opts.agent_env,
            "OPENAI_BASE_URL": f"{base}/v1", "OPENAI_API_KEY": "agentcrucible",
            "CRUCIBLE_MODEL": self.model, "CRUCIBLE_EPISODE_ID": eid,
            "PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8",
            **{f"CRUCIBLE_MCP_{n.upper()}_URL": f"{base}/mcp/{n}" for n in self.cfg.mcp_servers},
        }
        log_path = self.run_dir / "logs" / f"{eid}.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log = stack.enter_context(open(log_path, "w", encoding="utf-8"))
        cmd = split_command(agent.command or "")
        cwd = str((self.cfg.root / agent.cwd).resolve()) if agent.cwd else str(self.cfg.root)
        proc = await asyncio.create_subprocess_exec(
            *cmd, cwd=cwd, env=env, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log,
            limit=2**22,
        )

        async def _stop() -> None:
            if proc.returncode is None:
                with contextlib.suppress(Exception):
                    proc.stdin.write(b'{"type": "end"}\n')  # type: ignore[union-attr]
                    await proc.stdin.drain()  # type: ignore[union-attr]
                try:
                    await asyncio.wait_for(proc.wait(), 5)
                except asyncio.TimeoutError:
                    proc.kill()
                    await proc.wait()

        stack.push_async_callback(_stop)

        async def say(text: str) -> str:
            rec.turn += 1
            rec.add("user_message", content=text)
            proc.stdin.write((json.dumps({"type": "user", "content": text}) + "\n").encode())  # type: ignore[union-attr]
            await proc.stdin.drain()  # type: ignore[union-attr]
            while True:
                line = await asyncio.wait_for(proc.stdout.readline(), agent.turn_timeout_s)  # type: ignore[union-attr]
                if not line:
                    raise RuntimeError(f"agent exited (code {proc.returncode}); see {log_path.name}")
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue  # stray print() output from the agent
                if msg.get("type") == "assistant":
                    rec.add("assistant_message", content=msg.get("content", ""))
                    return msg.get("content", "")

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
