"""Reports: Markdown (PR comments, job summaries) and a self-contained HTML report."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .trajectory import load_events

ICON = {"regressed": "🔴 Regressed", "improved": "🟢 Improved", "inconclusive": "⚪ Inconclusive", "unchanged": "Unchanged"}
MARKER = "<!-- crucible-report -->"


def _p(x: float) -> str:
    return "–" if x != x else f"{x * 100:.0f}%"


def markdown_summary(run: dict[str, Any], comparison: dict[str, Any] | None) -> str:
    s = run["summary"]
    k = s["k"]
    lines = [MARKER, f"## 🧪 AgentCrucible · {run['project']}" + (f" · `{run['label']}`" if run.get("label") else ""), ""]
    if comparison:
        c, o = comparison["counts"], comparison["overall"]
        failed = c["regressed"] or o["verdict"] == "regressed"
        verdict = {"regressed": "**Overall pass rate regressed** (significant)",
                   "improved": "**Overall pass rate improved** (significant)",
                   "unchanged": "No significant overall change"}[o["verdict"]]
        lines.append(f"{'❌' if failed else '✅'} {verdict}: {o['delta'] * 100:+.1f} pts · "
                     f"scenarios: {c['regressed']} regressed · {c['improved']} improved · "
                     f"{c['inconclusive']} inconclusive · {c['unchanged']} unchanged")
        lines += ["", "| Scenario | baseline | this run | Δ | adj. p | Verdict |", "|---|---|---|---|---|---|"]
        for r in comparison["scenarios"]:
            extra = f" (needs k≈{r['runs_needed']})" if r.get("runs_needed") else ""
            lines.append(f"| `{r['scenario_id']}` | {r['base_passed']}/{r['base_n']} | {r['cand_passed']}/{r['cand_n']} | "
                         f"{r['delta'] * 100:+.0f} pts | {r['p_adj']:.3f} | {ICON[r['verdict']]}{extra} |")
        b = o["base"]
        lines += ["", f"**Overall pass@1** {_p(b['pass_at_1'])} → {_p(s['pass_at_1'])} "
                      f"(Δ {o['delta'] * 100:+.1f} pts, 95% CI {o['ci'][0] * 100:+.1f}…{o['ci'][1] * 100:+.1f}) → **{o['verdict']}**",
                  f"**Reliability pass^{k}** {_p(b['pass_pow_k'])} → {_p(s['pass_pow_k'])}"]
    else:
        lines += [f"**pass@1** {_p(s['pass_at_1'])} (95% CI {_p(s['pass_at_1_ci'][0])}–{_p(s['pass_at_1_ci'][1])}) · "
                  f"**pass^{k}** {_p(s['pass_pow_k'])} · pass@{k} {_p(s['pass_at_k'])}", "",
                  "| Scenario | passed | pass@1 |", "|---|---|---|"]
        for sid, v in s["scenarios"].items():
            lines.append(f"| `{sid}` | {v['passed']}/{v['n']} | {_p(v['pass_rate'])}{' ⚠ flaky' if v['flaky'] else ''} |")

    failures = _failure_reasons(run)
    if failures:
        lines += ["", "<details><summary>Why episodes failed</summary>", ""]
        for sid, reasons in failures.items():
            lines.append(f"- `{sid}`: " + "; ".join(f"{r} ({n}x)" for r, n in reasons.items()))
        lines += ["", "</details>"]
    lines += ["", f"<sub>{s['n_episodes']} episodes · model `{run['model']}` · {run['duration_s']:.0f}s · "
                  f"{s['tokens_per_episode']:.0f} tokens/episode · run `{run['run_id']}`</sub>"]
    return "\n".join(lines) + "\n"


def _failure_reasons(run: dict[str, Any]) -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for e in run["episodes"]:
        if e["passed"]:
            continue
        reasons = [e["error"]] if e.get("error") else [f"{c['label']}: {c['detail']}"[:140] for c in e["checks"]
                                                         if c["hard"] and not c["passed"]]
        bucket = out.setdefault(e["scenario_id"], {})
        for r in reasons:
            bucket[r] = bucket.get(r, 0) + 1
    return out


# ------------------------------------------------------------------ HTML


def write_html(run_dir: Path, run: dict[str, Any], comparison: dict[str, Any] | None) -> Path:
    trajectories = {}
    for e in run["episodes"]:
        f = run_dir / e["trajectory"]
        trajectories[e["episode_id"]] = load_events(f) if f.exists() else []
    data = {"run": run, "comparison": comparison, "trajectories": trajectories}
    payload = json.dumps(data, default=str).replace("</", "<\\/")
    title = f"AgentCrucible · {run['project']} · {run.get('label') or run['run_id']}"
    out = run_dir / "report.html"
    out.write_text(TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__DATA__", payload), encoding="utf-8")
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__</title>
<style>
:root{--bg:#f7f7f5;--panel:#fff;--ink:#1d1d1f;--mute:#6b6b70;--line:#e3e3e0;--red:#c8312b;--green:#1f8a4c;--amber:#b7791f;--accent:#3b5bdb;--code:#f1f1ee}
@media (prefers-color-scheme:dark){:root{--bg:#121214;--panel:#1b1b1f;--ink:#ececf1;--mute:#9a9aa3;--line:#2c2c33;--red:#ff6b62;--green:#4cc38a;--amber:#f0b54a;--accent:#7c9bff;--code:#24242a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}
header{padding:20px 24px;border-bottom:1px solid var(--line);background:var(--panel)}h1{font-size:18px;margin:0}
.sub{color:var(--mute);font-size:12.5px;margin-top:4px}main{padding:20px 24px;max-width:1400px;margin:auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:20px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 14px}
.card .k{color:var(--mute);font-size:12px}.card .v{font-size:22px;font-weight:600;font-variant-numeric:tabular-nums}.card .d{font-size:12px;color:var(--mute)}
table{width:100%;border-collapse:collapse;background:var(--panel);border:1px solid var(--line);border-radius:10px;overflow:hidden}
th,td{text-align:left;padding:8px 12px;border-bottom:1px solid var(--line);font-variant-numeric:tabular-nums}th{font-size:12px;color:var(--mute);font-weight:500}
tr.row{cursor:pointer}tr.row:hover td{background:var(--code)}tr.sel td{background:var(--code)}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:600}
.regressed{color:var(--red)}.improved{color:var(--green)}.inconclusive{color:var(--amber)}.unchanged{color:var(--mute)}
.dots span{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:3px;background:var(--line)}.dots .p{background:var(--green)}.dots .f{background:var(--red)}
.layout{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:16px;margin-top:16px}
@media (max-width:900px){.layout{grid-template-columns:1fr}}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:14px;min-width:0}
.eps button{font:inherit;border:1px solid var(--line);background:var(--bg);color:var(--ink);border-radius:8px;padding:4px 10px;margin:0 6px 6px 0;cursor:pointer}
.eps button.on{border-color:var(--accent);outline:1px solid var(--accent)}
.check{padding:6px 0;border-bottom:1px dashed var(--line);font-size:13px}.check:last-child{border:0}
.ev{display:grid;grid-template-columns:52px 22px minmax(0,1fr);gap:6px;padding:6px 0;border-bottom:1px solid var(--line);font-size:13px}
.ev .t{color:var(--mute);font-variant-numeric:tabular-nums;font-size:12px}.ev pre{margin:4px 0 0;white-space:pre-wrap;word-break:break-word;background:var(--code);padding:6px 8px;border-radius:6px;font-size:12px;max-height:240px;overflow:auto}
.ev.bad{background:color-mix(in srgb,var(--red) 8%,transparent)}.tag{font-size:11px;color:var(--mute);border:1px solid var(--line);border-radius:4px;padding:0 4px;margin-left:4px}
h2{font-size:15px;margin:22px 0 10px}.muted{color:var(--mute)}code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:12.5px}
</style></head><body>
<header><h1 id="title"></h1><div class="sub" id="sub"></div></header>
<main>
<div class="cards" id="cards"></div>
<h2>Scenarios</h2>
<table id="scen"><thead></thead><tbody></tbody></table>
<div class="layout"><div class="panel" id="left"><div class="muted">Select a scenario to see its episodes and checks.</div></div>
<div class="panel" id="right"><div class="muted">Trajectory viewer</div></div></div>
</main>
<script>
const D=__DATA__;const R=D.run,C=D.comparison,S=R.summary,T=D.trajectories;
const pct=x=>(x===null||x!==x)?'–':Math.round(x*100)+'%';const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
document.getElementById('title').textContent=`AgentCrucible · ${R.project}${R.label?' · '+R.label:''}`;
document.getElementById('sub').textContent=`${R.run_id} · model ${R.model} · ${S.n_scenarios} scenarios · ${S.n_episodes} episodes · ${Math.round(R.duration_s)}s · ${R.created_at.slice(0,19).replace('T',' ')}${R.git&&R.git.sha?' · git '+R.git.sha:''}`;
const card=(k,v,d='')=>`<div class="card"><div class="k">${k}</div><div class="v">${v}</div><div class="d">${d}</div></div>`;
let cards=card('pass@1',pct(S.pass_at_1),`95% CI ${pct(S.pass_at_1_ci[0])}–${pct(S.pass_at_1_ci[1])}`)+card(`pass^${S.k} (reliability)`,pct(S.pass_pow_k),'all attempts pass')+card(`pass@${S.k} (capability)`,pct(S.pass_at_k),'any attempt passes')+card('Flaky scenarios',S.flaky_scenarios.length,'pass sometimes, fail sometimes')+card('p95 episode time',S.duration_p95_s.toFixed(1)+'s',`p50 ${S.duration_p50_s.toFixed(1)}s`)+card('Tokens / episode',Math.round(S.tokens_per_episode),`errors ${S.errors}`);
if(C){const o=C.overall;cards=card('vs baseline',`<span class="${o.verdict}">${(o.delta*100>=0?'+':'')+(o.delta*100).toFixed(1)} pts</span>`,`95% CI ${(o.ci[0]*100).toFixed(1)}…${(o.ci[1]*100).toFixed(1)} · ${o.verdict}`)+card('Scenarios significantly regressed',`<span class="regressed">${C.counts.regressed}</span>`,`${C.counts.improved} improved · ${C.counts.inconclusive} inconclusive`)+cards}
document.getElementById('cards').innerHTML=cards;
const eps=sid=>R.episodes.filter(e=>e.scenario_id===sid).sort((a,b)=>a.attempt-b.attempt);
const dots=sid=>'<span class="dots">'+eps(sid).map(e=>`<span class="${e.passed?'p':'f'}"></span>`).join('')+'</span>';
const thead=document.querySelector('#scen thead'),tbody=document.querySelector('#scen tbody');
let rows;
if(C){thead.innerHTML='<tr><th>Scenario</th><th>Episodes</th><th>Baseline</th><th>This run</th><th>Δ</th><th>adj. p</th><th>Verdict</th></tr>';
rows=C.scenarios.map(r=>`<tr class="row" data-s="${esc(r.scenario_id)}"><td><b>${esc(r.scenario_id)}</b></td><td>${dots(r.scenario_id)}</td><td>${r.base_passed}/${r.base_n}</td><td>${r.cand_passed}/${r.cand_n}</td><td class="${r.verdict}">${(r.delta*100>=0?'+':'')+Math.round(r.delta*100)} pts</td><td>${r.p_adj.toFixed(3)}</td><td><span class="pill ${r.verdict}">${r.verdict}${r.runs_needed?' · needs k≈'+r.runs_needed:''}</span></td></tr>`)}
else{thead.innerHTML='<tr><th>Scenario</th><th>Episodes</th><th>Passed</th><th>pass@1</th><th>Tags</th></tr>';
rows=R.scenarios.map(sc=>{const v=S.scenarios[sc.id];return `<tr class="row" data-s="${esc(sc.id)}"><td><b>${esc(sc.id)}</b>${v.flaky?' <span class="pill inconclusive">flaky</span>':''}<div class="muted">${esc(sc.description)}</div></td><td>${dots(sc.id)}</td><td>${v.passed}/${v.n}</td><td>${pct(v.pass_rate)}</td><td>${sc.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</td></tr>`})}
tbody.innerHTML=rows.join('');
tbody.querySelectorAll('tr.row').forEach(tr=>tr.onclick=()=>{tbody.querySelectorAll('tr').forEach(x=>x.classList.remove('sel'));tr.classList.add('sel');showScenario(tr.dataset.s)});
function showScenario(sid){const list=eps(sid);const sc=R.scenarios.find(s=>s.id===sid)||{};
document.getElementById('left').innerHTML=`<div><b>${esc(sid)}</b></div><div class="muted" style="margin-bottom:10px">${esc(sc.description||'')}</div><div class="eps">${list.map((e,i)=>`<button data-e="${esc(e.episode_id)}">${e.passed?'✓':'✗'} attempt ${e.attempt}</button>`).join('')}</div><div id="checks"></div>`;
document.querySelectorAll('.eps button').forEach(b=>b.onclick=()=>{document.querySelectorAll('.eps button').forEach(x=>x.classList.remove('on'));b.classList.add('on');showEpisode(b.dataset.e)});
const first=list.find(e=>!e.passed)||list[0];if(first){document.querySelector(`.eps button[data-e="${CSS.escape(first.episode_id)}"]`).click()}}
function showEpisode(eid){const e=R.episodes.find(x=>x.episode_id===eid);const t=e.totals;
document.getElementById('checks').innerHTML=(e.error?`<div class="check regressed">Error: ${esc(e.error)}</div>`:'')+e.checks.map(c=>`<div class="check"><span class="${c.passed?'improved':(c.hard?'regressed':'inconclusive')}">${c.passed?'✓':'✗'}</span> <code>${esc(c.label)}</code>${c.hard?'':' <span class="tag">soft</span>'}<div class="muted">${esc(c.detail)}</div></div>`).join('')+`<div class="muted" style="margin-top:10px">${t.llm_calls} LLM calls · ${t.tokens_in+t.tokens_out} tokens · ${t.tool_calls} tool calls · ${t.turns} turns · ${t.duration_s.toFixed(1)}s</div>`;
const failedTools=new Set();e.checks.filter(c=>!c.passed).forEach(c=>{const m=c.detail.match(/^(\w+) called in turn|called forbidden: \[(.*)\]/);if(m){(m[1]||m[2]).split(',').forEach(x=>failedTools.add(x.replace(/['\s]/g,'')))}});
const ev=T[eid]||[];const icon={user_message:'👤',assistant_message:'🤖',llm_call:'🧠',tool_call:'🔧',tool_result:'↩',error:'⚠',episode_start:'▶',episode_end:'■'};
const body=ev.map(x=>{let main='',bad=false;switch(x.type){
case 'user_message':main=`<b>User</b> <span class="tag">turn ${x.turn}</span><pre>${esc(x.content)}</pre>`;break;
case 'assistant_message':main=`<b>Agent</b><pre>${esc(x.content)}</pre>`;break;
case 'llm_call':main=`LLM <code>${esc(x.model)}</code>${x.api?`<span class="tag">${esc(x.api)}${x.stream?' · stream':''}${x.cache&&x.cache!=='off'?' · '+esc(x.cache):''}</span>`:''} ${x.error?'<span class="regressed">'+esc(x.error)+'</span>':`${x.tokens_in}→${x.tokens_out} tok · ${Math.round(x.latency_ms)} ms${x.cache&&x.cache!=='off'?' · cache '+x.cache:''}${x.tool_calls&&x.tool_calls.length?' · wants '+x.tool_calls.map(esc).join(', '):''}`}`;break;
case 'tool_call':bad=failedTools.has(x.tool);main=`<b>${esc(x.server)}.${esc(x.tool)}</b>${x.blocked?'<span class="tag">blocked</span>':''}${x.mocked?'<span class="tag">mocked</span>':''}${x.injected?'<span class="tag">injected</span>':''}<pre>${esc(JSON.stringify(x.args,null,1))}</pre>`;break;
case 'tool_result':bad=x.is_error;main=`result ${x.is_error?'<span class="regressed">error</span>':''} <span class="muted">${x.latency_ms} ms</span><pre>${esc(x.content)}</pre>`;break;
case 'error':bad=true;main=`<span class="regressed">${esc(x.message)}</span>`;break;
default:main=`<span class="muted">${esc(x.type.replace('_',' '))}</span>`}
return `<div class="ev ${bad?'bad':''}"><div class="t">${x.t.toFixed(1)}s</div><div>${icon[x.type]||'·'}</div><div>${main}</div></div>`}).join('');
document.getElementById('right').innerHTML=`<div style="margin-bottom:8px"><b>Trajectory</b> <span class="muted">${esc(eid)}</span></div>${body||'<div class="muted">No events recorded.</div>'}`}
const firstBad=(C?C.scenarios.find(r=>r.verdict!=='unchanged'):null)||R.scenarios.find(s=>S.scenarios[s.id].passed<S.scenarios[s.id].n)||R.scenarios[0];
if(firstBad){const id=firstBad.scenario_id||firstBad.id;const tr=tbody.querySelector(`tr[data-s="${CSS.escape(id)}"]`);tr&&tr.click()}
</script></body></html>
"""
