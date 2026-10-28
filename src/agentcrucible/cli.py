"""Command-line interface."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import sys
import webbrowser
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.progress import BarColumn, MofNCompleteColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from . import __version__
from .config import load_config, load_scenarios
from .runner import EpisodeResult, Runner, RunOptions
from .stats import compare_runs, gate

app = typer.Typer(add_completion=False, no_args_is_help=True, pretty_exceptions_show_locals=False,
                  help="AgentCrucible: regression testing for AI agents and MCP servers.")
for _stream in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except Exception:
        pass
console = Console(legacy_windows=False)

VERDICT_STYLE = {"regressed": "bold red", "improved": "bold green", "inconclusive": "yellow", "unchanged": "dim"}


def _runs_dir(root: Path) -> Path:
    return root / ".crucible" / "runs"


def load_run(ref: str, root: Path) -> dict:
    """Load a run by id, 'latest', 'latest~1', a label, or a path to run.json."""
    p = Path(ref)
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    if (p / "run.json").is_file():
        return json.loads((p / "run.json").read_text(encoding="utf-8"))
    runs = sorted(_runs_dir(root).glob("run_*/run.json"))
    if not runs:
        raise typer.BadParameter("no runs found; run `crucible run` first")
    if ref.startswith("latest"):
        back = int(ref.split("~")[1]) if "~" in ref else 0
        return json.loads(runs[-1 - back].read_text(encoding="utf-8"))
    for f in reversed(runs):
        if f.parent.name == ref or f.parent.name.endswith(ref):
            return json.loads(f.read_text(encoding="utf-8"))
    for f in reversed(runs):  # match by label
        data = json.loads(f.read_text(encoding="utf-8"))
        if data.get("label") == ref:
            return data
    raise typer.BadParameter(f"run {ref!r} not found")


def _pct(x: float) -> str:
    return "–" if x != x else f"{x * 100:.0f}%"


@app.command()
def version() -> None:
    """Print the version."""
    console.print(f"agentcrucible {__version__}")


@app.command()
def validate(config: Path = typer.Option(None, "--config", "-c", help="Path to crucible.yaml")) -> None:
    """Validate crucible.yaml and every scenario file."""
    cfg = load_config(config)
    pairs = load_scenarios(cfg)
    console.print(f"[green]OK[/] {cfg.project}: {len(pairs)} scenarios across {len(cfg.suites)} suites, "
                  f"{len(cfg.mcp_servers)} MCP servers")
    for sc, runs in pairs:
        console.print(f"  • {sc.id} ({runs} runs, {len(sc.checks)} checks)")


@app.command()
def run(
    suite: Optional[str] = typer.Option(None, "--suite", "-s", help="Suite to run (default: all)"),
    scenario: Optional[list[str]] = typer.Option(None, "--scenario", help="Only these scenario ids"),
    runs: Optional[int] = typer.Option(None, "--runs", "-k", help="Override runs per scenario"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Override the agent's model"),
    parallel: int = typer.Option(2, "--parallel", "-p"),
    label: str = typer.Option("", "--label", "-l", help="Human label for this run, e.g. 'prompt-v2'"),
    env: Optional[list[str]] = typer.Option(None, "--env", "-e", help="Extra agent env KEY=VALUE"),
    cache: Optional[str] = typer.Option(None, "--cache", help="off | read_write | replay"),
    compare: Optional[str] = typer.Option(None, "--compare", help="Baseline run to compare against"),
    html: bool = typer.Option(True, "--html/--no-html", help="Write an HTML report"),
    shard: Optional[str] = typer.Option(None, "--shard", help="i/N: run only shard i of N "
                                        "(defaults to JOB_COMPLETION_INDEX / CRUCIBLE_SHARDS on Kubernetes)"),
    run_id: Optional[str] = typer.Option(None, "--run-id", help="Fixed run id (shards of one run share it)"),
    config: Path = typer.Option(None, "--config", "-c"),
) -> None:
    """Run scenarios and grade them."""
    cfg = load_config(config)
    pairs = load_scenarios(cfg, suite, scenario)
    if runs:
        pairs = [(sc, runs) for sc, _ in pairs]
    if not pairs:
        console.print("[red]No scenarios matched.[/]")
        raise typer.Exit(2)
    agent_env = dict(e.split("=", 1) for e in env or [])
    shard_t = None
    if shard is None and os.environ.get("JOB_COMPLETION_INDEX") and os.environ.get("CRUCIBLE_SHARDS"):
        shard = f"{os.environ['JOB_COMPLETION_INDEX']}/{os.environ['CRUCIBLE_SHARDS']}"
    if shard:
        i, n = (int(x) for x in shard.split("/"))
        shard_t = (i, n)
        compare = None  # shards are compared after `crucible merge`
    opts = RunOptions(label=label, parallel=parallel, model=model, agent_env=agent_env, cache=cache,
                      shard=shard_t, run_id=run_id or os.environ.get("CRUCIBLE_RUN_ID"))
    total = sum(r for _, r in pairs)
    if shard_t:
        total = len(range(shard_t[0], total, shard_t[1]))
    console.print(f"[bold]AgentCrucible[/] · {cfg.project} · {len(pairs)} scenarios · {total} episodes · "
                  f"model {model or cfg.model} · parallel {parallel}")

    with Progress(TextColumn("{task.description}"), BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(),
                  console=console) as progress:
        task = progress.add_task("episodes", total=total)

        def on_episode(r: EpisodeResult) -> None:
            mark = "[green]✓[/]" if r.passed else "[red]✗[/]"
            why = "" if r.passed else " — " + (r.error or "; ".join(c.label for c in r.checks if c.hard and not c.passed))
            progress.console.print(f"  {mark} {r.scenario_id} #{r.attempt}{why}")
            progress.advance(task)

        runner = Runner(cfg, opts, on_episode)
        result = asyncio.run(runner.run(pairs, suite))

    comparison = None
    if compare:
        base = load_run(compare, cfg.root)
        comparison = compare_runs(base, result, cfg.ci.alpha)
        (runner.run_dir / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    _print_run(result, comparison)
    _write_reports(runner.run_dir, result, comparison, html)
    ok, reasons = gate(comparison, result, cfg.ci.fail_on)
    console.print(f"\nRun saved: {runner.run_dir}")
    if shard_t:
        return  # gating happens on the merged run
    if not ok:
        console.print("[bold red]GATE FAILED:[/] " + "; ".join(reasons))
        raise typer.Exit(1)


@app.command("compare")
def compare_cmd(
    base: str = typer.Argument(..., help="Baseline run (id, label, 'latest~1', or path)"),
    cand: str = typer.Argument("latest", help="Candidate run"),
    config: Path = typer.Option(None, "--config", "-c"),
    html: bool = typer.Option(True, "--html/--no-html"),
) -> None:
    """Statistically compare two runs."""
    cfg = load_config(config)
    b, c = load_run(base, cfg.root), load_run(cand, cfg.root)
    comparison = compare_runs(b, c, cfg.ci.alpha)
    run_dir = _runs_dir(cfg.root) / c["run_id"]
    (run_dir / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    _print_run(c, comparison)
    _write_reports(run_dir, c, comparison, html)
    ok, reasons = gate(comparison, c, cfg.ci.fail_on)
    if not ok:
        console.print("[bold red]GATE FAILED:[/] " + "; ".join(reasons))
        raise typer.Exit(1)


@app.command()
def show(ref: str = typer.Argument("latest"), config: Path = typer.Option(None, "--config", "-c")) -> None:
    """Print a run summary."""
    cfg = load_config(config)
    _print_run(load_run(ref, cfg.root), None)


@app.command("open")
def open_cmd(ref: str = typer.Argument("latest"), config: Path = typer.Option(None, "--config", "-c")) -> None:
    """Open a run's HTML report in the browser."""
    cfg = load_config(config)
    r = load_run(ref, cfg.root)
    run_dir = _runs_dir(cfg.root) / r["run_id"]
    cmp_file = run_dir / "comparison.json"
    comparison = json.loads(cmp_file.read_text(encoding="utf-8")) if cmp_file.exists() else None
    _write_reports(run_dir, r, comparison, html=True)
    webbrowser.open((run_dir / "report.html").resolve().as_uri())


@app.command("mcp-audit")
def mcp_audit(
    command: Optional[str] = typer.Option(None, "--command", help="Command that starts the server over stdio"),
    url: Optional[str] = typer.Option(None, "--url", help="Streamable HTTP URL of a running server"),
    env: Optional[list[str]] = typer.Option(None, "--env", "-e", help="Server env KEY=VALUE"),
    cwd: Optional[Path] = typer.Option(None, "--cwd"),
    fixture: Optional[Path] = typer.Option(None, "--fixture", help="SQL seed; a fresh SQLite DB is passed as CRUCIBLE_DB"),
    destructive: bool = typer.Option(False, "--destructive/--safe", help="Also fuzz tools that look destructive"),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Run the behavioral suite with this model"),
    llm_url: str = typer.Option("http://localhost:11434/v1", "--llm-url"),
    llm_key: str = typer.Option("ollama", "--llm-key"),
    out: Path = typer.Option(Path(".crucible/audits"), "--out"),
    fail_under: int = typer.Option(0, "--fail-under", help="Exit 1 if the overall score is below this"),
) -> None:
    """Audit an MCP server: conformance, tool quality, fuzzing, security, behavior, performance."""
    from .audit import SEV_ICON, SEV_ORDER, audit_junit, audit_markdown, letter, run_audit
    if not command and not url:
        raise typer.BadParameter("give --command or --url")
    console.print(f"[bold]MCP audit[/] · {url or command}")
    rep = asyncio.run(run_audit(command, url, dict(e.split("=", 1) for e in env or []),
                                str(cwd) if cwd else None, fixture, destructive, model, llm_url, llm_key))
    t = Table(title=f"{rep.server_name} · grade {rep.grade} ({rep.overall}/100)")
    t.add_column("Suite")
    t.add_column("Score", justify="right")
    t.add_column("Findings", justify="right")
    for s, score in rep.scores.items():
        t.add_row(s.replace("_", " "), f"{score} ({letter(score)})", str(sum(1 for f in rep.findings if f.suite == s)))
    console.print(t)
    for f in sorted(rep.findings, key=lambda f: SEV_ORDER[f.severity]):
        console.print(f"{SEV_ICON[f.severity]} [bold]{f.severity}[/] {f.suite} · {('[cyan]' + f.tool + '[/] · ') if f.tool else ''}{f.title}"
                      + (f"\n    [dim]{f.detail}[/]" if f.detail else ""))
    out.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", rep.server_name or "server")
    (out / f"{stem}.json").write_text(json.dumps(rep.to_dict(), indent=2), encoding="utf-8")
    (out / f"{stem}.md").write_text(audit_markdown(rep), encoding="utf-8")
    (out / f"{stem}.junit.xml").write_text(audit_junit(rep), encoding="utf-8")
    console.print(f"\nSaved {out / stem}.(json|md|junit.xml) · {rep.duration_s}s")
    if rep.overall < fail_under:
        raise typer.Exit(1)


@app.command()
def label(
    ref: str = typer.Argument("latest", help="Run whose episodes you want to label"),
    criteria: str = typer.Option(..., "--criteria", help="The rubric text, exactly as used in judge.rubric"),
    scenario: Optional[list[str]] = typer.Option(None, "--scenario"),
    limit: int = typer.Option(50, "--limit"),
    labeler: str = typer.Option("human", "--labeler"),
    config: Path = typer.Option(None, "--config", "-c"),
) -> None:
    """Hand-label episodes 1-5 against a rubric (keys: 1-5, s = skip, q = quit)."""
    from rich.panel import Panel

    from .calibration import load_labels, save_label
    from .trajectory import Recorder, load_events
    cfg = load_config(config)
    r = load_run(ref, cfg.root)
    done = load_labels(cfg.root, criteria)
    todo = [e for e in r["episodes"] if e["episode_id"] not in done and (not scenario or e["scenario_id"] in scenario)]
    console.print(f"[bold]Labeling[/] {len(todo)} unlabeled episodes ({len(done)} already labeled)\nRubric: [cyan]{criteria}[/]")
    n = 0
    for e in todo[:limit]:
        rec = Recorder(e["episode_id"], e["scenario_id"], e["attempt"])
        rec.events = load_events(_runs_dir(cfg.root) / r["run_id"] / e["trajectory"])
        console.print(Panel(rec.transcript or "(empty)", title=f"{e['scenario_id']} #{e['attempt']}", expand=False))
        ans = typer.prompt("score 1-5 / s / q").strip().lower()
        if ans == "q":
            break
        if ans not in {"1", "2", "3", "4", "5"}:
            continue
        save_label(cfg.root, criteria, {"episode_id": e["episode_id"], "run_id": r["run_id"],
                                        "trajectory": e["trajectory"], "human": int(ans), "labeler": labeler})
        n += 1
    console.print(f"Saved {n} labels.")


@app.command()
def calibrate(
    criteria: str = typer.Option(..., "--criteria"),
    threshold: int = typer.Option(4, "--threshold", help="Score at or above which an episode passes"),
    config: Path = typer.Option(None, "--config", "-c"),
) -> None:
    """Score labeled episodes with the judge and measure agreement (Cohen's kappa)."""
    import httpx

    from .calibration import calibration_path, load_labels, summarize
    from .checks import GradeContext, judge_score
    from .trajectory import Recorder, load_events
    cfg = load_config(config)
    labels = load_labels(cfg.root, criteria)
    if len(labels) < 10:
        console.print(f"[yellow]Only {len(labels)} labels; label at least 10 (ideally 50+) first.[/]")
        raise typer.Exit(2)

    async def go() -> list[dict]:
        pairs = []
        async with httpx.AsyncClient(timeout=300) as http:
            ctx = GradeContext(dbs={}, judge=cfg.judge, http=http)
            for row in labels.values():
                f = _runs_dir(cfg.root) / row["run_id"] / row["trajectory"]
                if not f.exists():
                    continue
                rec = Recorder(row["episode_id"], "", 0)
                rec.events = load_events(f)
                score, reason = await judge_score(ctx, criteria, rec.transcript)
                pairs.append({"episode_id": row["episode_id"], "human": row["human"], "judge": score, "reason": reason})
        return pairs

    with console.status(f"judging {len(labels)} episodes with {cfg.judge.model}..."):
        pairs = asyncio.run(go())
    out = summarize(criteria, threshold, pairs, cfg.judge.model)
    f = calibration_path(cfg.root, criteria)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(out, indent=2), encoding="utf-8")
    style = {"trusted": "green", "advisory": "yellow", "disabled": "red"}.get(out["status"], "white")
    c = out["confusion"]
    console.print(f"Judge [bold]{cfg.judge.model}[/] vs {out['n']} human labels\n"
                  f"  kappa (pass/fail @ >= {threshold}): [bold]{out['kappa_pass_fail']:.2f}[/]   "
                  f"quadratic kappa (1-5): {out['kappa_quadratic_1to5']:.2f}   agreement {out['agreement'] * 100:.0f}%\n"
                  f"  judge pass & human pass {c['judge_pass_human_pass']} · judge pass & human fail {c['judge_pass_human_fail']} · "
                  f"judge fail & human pass {c['judge_fail_human_pass']} · both fail {c['judge_fail_human_fail']}\n"
                  f"  status: [{style}]{out['status']}[/]" + ("" if out["status"] == "trusted" else
                                                            " → judge.rubric checks with this criteria can no longer fail a run"))
    for d in out["disagreements"][:5]:
        console.print(f"  [dim]{d['episode_id']}: human {d['human']} vs judge {d['judge']} — {d['reason'][:100]}[/]")


@app.command()
def merge(
    shards: list[Path] = typer.Argument(..., help="Shard run directories (or run.json files)"),
    label: str = typer.Option("", "--label", "-l"),
    compare: Optional[str] = typer.Option(None, "--compare"),
    config: Path = typer.Option(None, "--config", "-c"),
) -> None:
    """Merge shard runs (e.g. from a Kubernetes Indexed Job) into one run, then compare and gate."""
    from .stats import summarize_run
    cfg = load_config(config)
    parts = [load_run(str(p), cfg.root) for p in shards]
    base_id = parts[0]["run_id"].split("-shard")[0]
    run_dir = _runs_dir(cfg.root) / base_id
    (run_dir / "episodes").mkdir(parents=True, exist_ok=True)
    episodes = []
    for part, src in zip(parts, shards, strict=False):
        src_dir = src if src.is_dir() else src.parent
        for e in part["episodes"]:
            f = src_dir / e["trajectory"]
            if f.exists() and f.resolve() != (run_dir / e["trajectory"]).resolve():
                shutil.copy(f, run_dir / e["trajectory"])
            episodes.append(e)
    merged = {**parts[0], "run_id": base_id, "label": label or parts[0].get("label", ""), "shard": None,
              "episodes": episodes, "duration_s": max(p["duration_s"] for p in parts),
              "merged_from": [p["run_id"] for p in parts]}
    merged["summary"] = summarize_run(merged)
    (run_dir / "run.json").write_text(json.dumps(merged, indent=2), encoding="utf-8")
    comparison = compare_runs(load_run(compare, cfg.root), merged, cfg.ci.alpha) if compare else None
    if comparison:
        (run_dir / "comparison.json").write_text(json.dumps(comparison, indent=2), encoding="utf-8")
    _print_run(merged, comparison)
    _write_reports(run_dir, merged, comparison, True)
    ok, reasons = gate(comparison, merged, cfg.ci.fail_on)
    if not ok:
        console.print("[bold red]GATE FAILED:[/] " + "; ".join(reasons))
        raise typer.Exit(1)


@app.command()
def init(path: Path = typer.Argument(Path("."))) -> None:
    """Create a starter crucible.yaml and an example scenario."""
    from .config import CONFIG_FILENAME
    path.mkdir(parents=True, exist_ok=True)
    cfg_file = path / CONFIG_FILENAME
    if cfg_file.exists():
        console.print(f"[yellow]{cfg_file} already exists[/]")
        raise typer.Exit(1)
    cfg_file.write_text(STARTER_CONFIG, encoding="utf-8")
    sc_dir = path / "scenarios" / "smoke"
    sc_dir.mkdir(parents=True, exist_ok=True)
    (sc_dir / "hello.yaml").write_text(STARTER_SCENARIO, encoding="utf-8")
    console.print(f"Created {cfg_file} and {sc_dir / 'hello.yaml'}.\n"
                  "Edit agent.command and mcp_servers, then run [bold]crucible validate[/] and [bold]crucible run[/].")


STARTER_CONFIG = """version: 1
project: my-agent

# AgentCrucible starts your agent once per episode and injects:
#   OPENAI_BASE_URL / OPENAI_API_KEY   -> its LLM gateway (records, caches, forces the model)
#   CRUCIBLE_MCP_<NAME>_URL          -> one MCP proxy per server below
#   CRUCIBLE_MODEL                   -> the model under test
# Agent protocol (stdio): read {"type":"user","content":...} lines, write {"type":"assistant","content":...} lines.
agent:
  transport: stdio
  command: python agent.py

model: qwen2.5:7b
llm:
  upstream_base_url: http://localhost:11434/v1   # any OpenAI-compatible API: Ollama, vLLM, OpenAI, OpenRouter, Groq
  api_key: ollama

mcp_servers: {}
#  shop: { command: python mcp/shop_server.py }

simulator: { model: qwen2.5:7b }
judge: { model: qwen2.5:7b, temperature: 0 }

suites:
  smoke: { path: scenarios/smoke, runs: 3 }

ci:
  fail_on: [regressed]
"""

STARTER_SCENARIO = """id: hello
description: The agent greets the user and offers help.
task: Hi there!
checks:
  - output.regex: { pattern: "help|assist" }
  - trajectory.max_tool_calls: 0
  - judge.rubric: { criteria: "The reply is friendly and offers help.", min: 4, hard: false }
"""


# ---------------------------------------------------------------- output helpers


def _write_reports(run_dir: Path, run: dict, comparison: dict | None, html: bool) -> None:
    from .report import markdown_summary, write_html
    (run_dir / "summary.md").write_text(markdown_summary(run, comparison), encoding="utf-8")
    if html:
        write_html(run_dir, run, comparison)
        console.print(f"Report: {run_dir / 'report.html'}")


def _print_run(run: dict, comparison: dict | None) -> None:
    s = run["summary"]
    t = Table(title=f"{run['run_id']} {('· ' + run['label']) if run.get('label') else ''}", show_lines=False)
    t.add_column("Scenario")
    t.add_column(f"pass^{s['k']}", justify="right")
    t.add_column("pass@1", justify="right")
    if comparison:
        t.add_column("vs baseline", justify="right")
        t.add_column("verdict")
        for row in comparison["scenarios"]:
            sc = s["scenarios"][row["scenario_id"]]
            extra = f" (needs k≈{row['runs_needed']})" if row.get("runs_needed") else ""
            t.add_row(row["scenario_id"], f"{sc['passed']}/{sc['n']}", _pct(sc["pass_rate"]),
                      f"{_pct(row['base_rate'])} → {_pct(row['cand_rate'])}",
                      f"[{VERDICT_STYLE[row['verdict']]}]{row['verdict']}{extra}[/]")
    else:
        for sid, sc in s["scenarios"].items():
            flake = " [yellow](flaky)[/]" if sc["flaky"] else ""
            t.add_row(sid + flake, f"{sc['passed']}/{sc['n']}", _pct(sc["pass_rate"]))
    console.print(t)
    lo, hi = s["pass_at_1_ci"]
    console.print(f"pass@1 [bold]{_pct(s['pass_at_1'])}[/] (95% CI {_pct(lo)}–{_pct(hi)}) · "
                  f"pass^{s['k']} [bold]{_pct(s['pass_pow_k'])}[/] · pass@{s['k']} {_pct(s['pass_at_k'])} · "
                  f"errors {s['errors']} · p95 {s['duration_p95_s']:.1f}s · "
                  f"{s['tokens_per_episode']:.0f} tokens/episode")
    if comparison:
        o = comparison["overall"]
        style = VERDICT_STYLE[o["verdict"]]
        console.print(f"Overall vs {comparison['base_run']}: Δ {o['delta'] * 100:+.1f} pts "
                      f"(95% CI {o['ci'][0] * 100:+.1f}…{o['ci'][1] * 100:+.1f}) → [{style}]{o['verdict']}[/]")


def main() -> None:  # pragma: no cover
    try:
        app(standalone_mode=True)
    except KeyboardInterrupt:
        sys.exit(130)
    except (ValueError, FileNotFoundError, KeyError) as e:
        console.print(f"[red]error:[/] {e}")
        sys.exit(2)


if __name__ == "__main__":  # pragma: no cover
    main()
