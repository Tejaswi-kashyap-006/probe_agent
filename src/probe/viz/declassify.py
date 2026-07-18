"""The declassification race.

The hidden contract as a redacted document, with two agents racing to un-redact
it. Each rule uncovers at the probe index where that agent first confirmed it.
An API is invisible, so the thing worth showing is not a number going up but
uncertainty dying.

Self-contained HTML and inline JS. The reveal schedule comes from the trace;
nothing is typed in by hand.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from probe.viz.trace_export import RunView, first_confirmed_at

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>Declassification race</title>
<style>
:root{color-scheme:light dark;--bg:#ffffff;--fg:#111827;--muted:#6b7280;
--bar:#e5e7eb;--ink:#111827;--hit:#2563eb;--cp:#b45309}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f19;--fg:#f3f4f6;--muted:#9ca3af;
--bar:#1f2937;--ink:#e5e7eb;--hit:#60a5fa;--cp:#fbbf24}}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--bg);color:var(--fg);
font-family:ui-sans-serif,system-ui,-apple-system,sans-serif}
h1{font-size:17px;margin:0 0 4px}
p.sub{margin:0 0 20px;color:var(--muted);font-size:13px}
.race{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px}
@media(max-width:760px){.race{grid-template-columns:1fr}}
.col{border:1px solid var(--bar);border-radius:8px;padding:14px;min-width:0}
.hdr{display:flex;justify-content:space-between;align-items:baseline;
margin-bottom:10px}
.name{font-weight:600;font-size:14px}
.count{font-variant-numeric:tabular-nums;color:var(--muted);font-size:12px}
.rule{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11.5px;
padding:3px 6px;margin:3px 0;border-radius:4px;background:var(--bar);
color:transparent;transition:color .35s,background .35s;overflow-wrap:anywhere}
.rule.on{background:transparent;color:var(--ink)}
.rule.on.cp{color:var(--cp)}
.meter{height:4px;background:var(--bar);border-radius:2px;margin-top:10px}
.fill{height:100%;width:0;background:var(--hit);border-radius:2px;
transition:width .35s}
button{margin-top:18px;padding:7px 14px;font-size:13px;border-radius:6px;
border:1px solid var(--bar);background:transparent;color:var(--fg);cursor:pointer}
.legend{margin-top:14px;color:var(--muted);font-size:11.5px}
@media(prefers-reduced-motion:reduce){.rule,.fill{transition:none}}
</style>
<h1>Recovering a hidden API contract</h1>
<p class="sub">Every rule starts redacted. Each uncovers at the probe where that
agent first confirmed it. Amber rules are counter-prior &mdash; the ones that cannot
be guessed from convention.</p>
<div class="race" id="race"></div>
<button id="replay">Replay</button>
<div class="legend" id="legend"></div>
<script>
const DATA = __DATA__;

const race = document.getElementById('race');
const legend = document.getElementById('legend');
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;

const cols = DATA.agents.map(agent => {
  const col = document.createElement('div');
  col.className = 'col';
  col.innerHTML = `<div class="hdr"><span class="name">${agent.name}</span>
    <span class="count" data-count>0 probes</span></div>`;
  const rules = DATA.rules.map(rule => {
    const el = document.createElement('div');
    el.className = 'rule' + (rule.counter_prior ? ' cp' : '');
    el.textContent = rule.text;
    col.appendChild(el);
    return el;
  });
  const meter = document.createElement('div');
  meter.className = 'meter';
  const fill = document.createElement('div');
  fill.className = 'fill';
  meter.appendChild(fill);
  col.appendChild(meter);
  race.appendChild(col);
  return {agent, rules, fill, count: col.querySelector('[data-count]')};
});

legend.textContent = DATA.rules.length + ' rules \\u00b7 budget ' +
  DATA.budget + ' probes \\u00b7 variant ' + DATA.variant;

function frame(probe){
  for (const col of cols){
    let found = 0;
    col.rules.forEach((el, i) => {
      const at = col.agent.reveal[DATA.rules[i].id];
      const on = at !== null && at !== undefined && at <= probe;
      el.classList.toggle('on', on);
      if (on) found++;
    });
    col.count.textContent = Math.min(probe, col.agent.probes) + ' probes \\u00b7 ' +
      found + '/' + DATA.rules.length + ' recovered';
    col.fill.style.width = (100 * found / DATA.rules.length) + '%';
  }
}

function play(){
  if (reduce){ frame(DATA.budget); return; }
  let probe = 0;
  frame(0);
  const step = Math.max(1, Math.round(DATA.budget / 60));
  const timer = setInterval(() => {
    probe += step;
    frame(probe);
    if (probe >= DATA.budget) clearInterval(timer);
  }, 90);
}

document.getElementById('replay').addEventListener('click', play);
play();
</script>
"""


def _describe(rule: dict[str, Any]) -> str:
    kind = rule.get("kind")
    param = rule.get("param") or f"{rule.get('param_a')}/{rule.get('param_b')}"
    endpoint = rule.get("endpoint", "")
    body = {
        "required": f"{param} is required",
        "optional": f"{param} defaults to {rule.get('default')}",
        "type": f"{param} must be {rule.get('type_name')}",
        "range": f"{rule.get('lo')} <= {param} <= {rule.get('hi')}",
        "enum": f"{param} in {{{', '.join(rule.get('values') or [])}}}",
        "format": f"{param} matches {rule.get('pattern')}",
        "pagination_cap": f"{param} caps at {rule.get('cap')}",
        "conditional_required": (
            f"{rule.get('if_param')}={rule.get('if_value')} requires "
            f"{rule.get('then_param')}"
        ),
        "mutual_exclusion": f"{rule.get('param_a')} excludes {rule.get('param_b')}",
        "resource_lookup": f"unknown {param} returns {rule.get('status')}",
    }.get(str(kind), str(kind))
    status = rule.get("status")
    suffix = f" -> {status}" if status else ""
    return f"{endpoint}  {body}{suffix}"


def render(
    views: list[RunView],
    truth: list[dict[str, Any]],
    out: Path,
    budget: int = 100,
) -> Path | None:
    if not views:
        return None

    rules = [
        {
            "id": rule.get("id", ""),
            "text": _describe(rule),
            "counter_prior": rule.get("prior_class") == "counter_prior",
        }
        for rule in truth
    ]
    truth_ids = [r["id"] for r in rules]

    agents = [
        {
            "name": view.agent,
            "probes": len(view.probes),
            "reveal": first_confirmed_at(view, truth_ids),
        }
        for view in views
    ]

    data = {
        "rules": rules,
        "agents": agents,
        "budget": budget,
        "variant": views[0].variant,
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
