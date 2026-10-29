"""Measure the codebase import on real open-source agent repositories.

For each repository in repos.json (pinned to a commit): clone it, install its dependencies in its own virtualenv,
then time the import the way a user runs it: scan with the local model writing descriptions, apply the reviewer's
edits listed for that repository (each one counts as an edit), write the tests and smoke-run them once each. Clone and
install time is reported separately.

The repositories' code runs during the smoke run, so run this in the throwaway container (benchmarks/Dockerfile),
never on your machine:

    docker build -f benchmarks/Dockerfile -t agentcrucible-bench .
    docker run --rm --network agentcrucible_default -v "$PWD/.bench:/work" agentcrucible-bench

Writes /work/results.json and /work/results.md.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
SRC = Path(os.environ.get("CRUCIBLE_SRC", HERE.parent))


def sh(cmd: list[str], cwd: Path | None = None, timeout: int = 1800) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)


def prepare(repo: dict[str, Any], work: Path) -> tuple[Path, float, list[str]]:
    """Clone at the pinned commit and install the dependencies. Returns (agent root, seconds, notes)."""
    start = time.time()
    notes: list[str] = []
    checkout = work / repo["name"]
    if not (checkout / ".git").is_dir():
        shutil.rmtree(checkout, ignore_errors=True)
        checkout.mkdir(parents=True)
        for cmd in (["git", "init", "-q"], ["git", "remote", "add", "origin", repo["url"]],
                    ["git", "fetch", "-q", "--depth", "1", "origin", repo["commit"]], ["git", "checkout", "-q", "FETCH_HEAD"]):
            r = sh(cmd, checkout, 900)
            if r.returncode:
                raise RuntimeError(f"{' '.join(cmd)}: {r.stderr.strip()[:300]}")
    root = checkout / repo.get("path", ".")
    venv = root / ".venv"
    if not (venv / "bin" / "python").exists():
        r = sh(["uv", "venv", "-q", "--clear", "--python", repo.get("python", "3.12"), str(venv)], root)  # --clear: a half-made one
        if r.returncode:
            raise RuntimeError(f"uv venv: {r.stderr.strip()[:300]}")
    py = str(venv / "bin" / "python")
    installs: list[list[str]] = []
    if (root / "requirements.txt").is_file():
        installs.append(["-r", "requirements.txt"])
    elif (root / "pyproject.toml").is_file():
        installs.append(["-e", "."])
    if repo.get("install"):
        installs.append(list(repo["install"]))
    installs.append([str(SRC)])  # the adapters import agentcrucible from the agent's own environment
    for args in installs:
        r = sh(["uv", "pip", "install", "-q", "--python", py, *args], root, 1800)
        if r.returncode and args == ["-e", "."]:  # a pyproject.toml that isn't a buildable package: its dependencies
            import tomllib
            deps = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8")).get("project", {}).get("dependencies", [])
            if deps:
                r = sh(["uv", "pip", "install", "-q", "--python", py, *deps], root, 1800)
                notes.append("not a package: installed the dependencies from pyproject.toml")
        if r.returncode:
            notes.append(f"install {' '.join(args)[:60]} failed: {r.stderr.strip().splitlines()[-1][:200] if r.stderr.strip() else ''}")
    return root, time.time() - start, notes


def apply_edits(d: Any, edits: list[dict[str, Any]]) -> list[str]:
    """A reviewer's changes, recorded per repository so they can be counted (and re-applied on every run)."""
    from agentcrucible.server_discover import answer_questions
    done = []
    for e in edits:
        if "answer" in e:
            q = next((q for q in d.questions if q.about == e["answer"]), None)
            if q:
                answer_questions(d, {q.id: e["value"]})
                done.append(f"answered {e['answer']}: {e['value']}")
        elif "include_agent" in e:
            ag = d.agent(e["include_agent"])
            if ag:
                ag.include = bool(e.get("value", True))
                done.append(f"{'included' if ag.include else 'excluded'} agent {ag.id}")
        elif "mock_tool" in e:
            t = d.tool(e["mock_tool"])
            if t:
                t.mock = True
                done.append(f"mocked tool {t.name}")
        elif "env" in e:
            os.environ.update(e["env"])
            done.append(f"set {', '.join(e['env'])}")
    return done


def measure(repo: dict[str, Any], root: Path, url: str, model: str) -> dict[str, Any]:
    from agentcrucible.discover import apply, build_plan, discover

    out: dict[str, Any] = {}
    log = open(root.parent / f"{repo['name']}.progress.log", "a", encoding="utf-8")  # survives a timeout

    def say(msg: str) -> None:
        log.write(f"{time.time() - t0:7.1f}s {msg}\n")
        log.flush()

    t0 = time.time()
    d = discover(root, include=repo.get("include"), llm_base_url=url, llm_model=model, progress=say)  # include: one example of a big repo
    build_plan(d, root)
    out["discover_s"] = round(time.time() - t0, 1)
    out["agents_found"] = [a.id for a in d.agents]
    out["agents"] = [a.id for a in d.agents if a.include]
    out["frameworks"] = d.repo.frameworks
    out["tools"] = len(d.tools)
    out["questions"] = [q.text for q in d.questions]
    edits = apply_edits(d, repo.get("edits", []))
    if edits:
        build_plan(d, root)
    out["edits"] = edits
    out["strategies"] = {p.agent: p.strategy for p in d.plans}
    out["scenarios"] = sum(1 for s in d.scenarios if s.include)
    if not out["agents"]:  # a library or examples-in-tests repo: correctly nothing to test
        out.update(time_to_smoke_s=round(time.time() - t0, 1), smoke=None, green=None,
                   note="no agent to test: " + "; ".join(n for a in d.agents for n in a.notes)[:200])
        return out
    t1 = time.time()
    result = apply(d, root, model=model, upstream=url, smoke=True, progress=say,
                   on_episode=lambda r: say(f"{'pass' if r.passed else 'fail'} {r.scenario_id}"))
    out["apply_s"] = round(time.time() - t1, 1)
    out["time_to_smoke_s"] = round(time.time() - t0, 1)
    rep = result.get("reality") or {}
    out["smoke"] = {k: rep.get(k) for k in ("episodes", "passed", "errors")} if rep else None
    out["connection"] = [c for c in result.get("connection", []) if not c["ok"]]
    out["findings"] = [f"{f['kind']}: {f['detail'][:200]}" for f in rep.get("findings", [])][:12]
    out["failed"] = [f"{s['scenario']}: {(s.get('error') or '; '.join(c['check'] for c in s['failed']))[:160]}"
                     for s in rep.get("scenarios", []) if not s["passed"]][:12]
    out["green"] = bool(rep) and rep.get("errors") == 0 and rep.get("episodes", 0) > 0
    return out


def one(name: str, work: Path, url: str, model: str) -> dict[str, Any]:
    repo = next(r for r in json.loads((HERE / "repos.json").read_text()) if r["name"] == name)
    res: dict[str, Any] = {"name": name, "framework": repo["framework"], "url": repo["url"], "commit": repo["commit"][:12],
                           "path": repo.get("path", ".")}
    try:
        root, setup_s, notes = prepare(repo, work)
        (root.parent / f"{name}.progress.log").write_text(f"setup {setup_s:.0f}s {notes}\n", encoding="utf-8")
        res.update(setup_s=round(setup_s, 1), setup_notes=notes)
        res.update(measure(repo, root, url, model))
    except Exception as e:  # noqa: BLE001 - one broken repository shouldn't stop the benchmark
        res["error"] = f"{type(e).__name__}: {str(e)[:500]}"
    return res


def markdown(results: list[dict[str, Any]]) -> str:
    rows = ["| Repository | Framework | Agents | Questions | Edits | Path → smoke run | Smoke (passed / ran, errors) |",
            "|---|---|---|---|---|---|---|"]
    for r in results:
        sm = r.get("smoke") or {}
        smoke = (f"{sm.get('passed')}/{sm.get('episodes')}, {sm.get('errors')} errors" if sm
                 else "nothing to test (correct: no agent outside tests)" if r.get("note", "").startswith("no agent")
                 else (r.get("error") or "no smoke run").splitlines()[0][:80])
        mins = f"{r['time_to_smoke_s'] / 60:.1f} min" if "time_to_smoke_s" in r else "–"
        rows.append(f"| {r['name']} | {r['framework']} | {len(r.get('agents', []))} | {len(r.get('questions', []))} | "
                    f"{len(r.get('edits', []))} | {mins} | {smoke} |")
    done = [r for r in results if "time_to_smoke_s" in r and r.get("smoke")]
    green = [r for r in done if r.get("green")]
    under = [r for r in green if r["time_to_smoke_s"] <= 600]
    edits = sum(len(r.get("edits", [])) for r in done) / max(len(done), 1)
    qs = sum(len(r.get("questions", [])) for r in done) / max(len(done), 1)
    rows += ["", f"Smoke runs without agent errors: {len(green)}/{len(results)} · of those under 10 minutes: {len(under)} · "
                 f"edits per review: {edits:.1f} · questions per repository: {qs:.1f}"]
    return "\n".join(rows) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, default=Path("/work"))
    ap.add_argument("--only", nargs="*")
    ap.add_argument("--one")  # internal: run one repository (in a subprocess with a time limit)
    ap.add_argument("--timeout", type=int, default=3600)
    a = ap.parse_args()
    url = os.environ.get("CRUCIBLE_LLM_URL", "http://models:11434/v1")
    model = os.environ.get("CRUCIBLE_MODEL", "qwen2.5:7b")
    a.work.mkdir(parents=True, exist_ok=True)
    if a.one:
        print(json.dumps(one(a.one, a.work, url, model)))
        return
    repos = [r["name"] for r in json.loads((HERE / "repos.json").read_text()) if not a.only or r["name"] in a.only]
    results_file = a.work / "results.json"
    results = {r["name"]: r for r in json.loads(results_file.read_text())} if results_file.exists() else {}
    for name in repos:
        print(f"== {name}", flush=True)
        try:
            p = subprocess.run([sys.executable, __file__, "--work", str(a.work), "--one", name], capture_output=True,
                               text=True, timeout=a.timeout)
            lines = [ln for ln in p.stdout.splitlines() if ln.startswith("{")]
            res = json.loads(lines[-1]) if lines else {"name": name, "error": (p.stderr or "no output").strip()[-500:]}
        except subprocess.TimeoutExpired:
            res = {"name": name, "error": f"timed out after {a.timeout}s"}
        res.setdefault("framework", next(r["framework"] for r in json.loads((HERE / "repos.json").read_text()) if r["name"] == name))
        results[name] = res
        print(json.dumps({k: res.get(k) for k in ("agents", "time_to_smoke_s", "smoke", "error")}), flush=True)
        results_file.write_text(json.dumps(list(results.values()), indent=2))
    ordered = [results[n] for n in [r["name"] for r in json.loads((HERE / "repos.json").read_text())] if n in results]
    (a.work / "results.md").write_text(markdown(ordered))
    print(markdown(ordered))


if __name__ == "__main__":
    main()
