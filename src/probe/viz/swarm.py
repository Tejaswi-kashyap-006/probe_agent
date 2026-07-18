"""Hypothesis swarm: a cloud of candidate contracts collapsing to a point.

One dot per surviving particle. After each probe the ones that predicted wrongly
fade out. Re-proposals — the moments where every hypothesis a factor held turned
out to be wrong — arrive as a burst of new dots, and those are the most
interesting events in the run.
"""

from __future__ import annotations

import json
from pathlib import Path

from probe.viz.trace_export import RunView

TEMPLATE = """<!doctype html>
<meta charset="utf-8">
<title>Hypothesis swarm</title>
<style>
:root{color-scheme:light dark;--bg:#ffffff;--fg:#111827;--muted:#6b7280;--dot:#2563eb;
--burst:#dc2626;--grid:#e5e7eb}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f19;--fg:#f3f4f6;--muted:#9ca3af;
--dot:#60a5fa;--burst:#f87171;--grid:#1f2937}}
*{box-sizing:border-box}
body{margin:0;padding:28px;background:var(--bg);color:var(--fg);
font-family:ui-sans-serif,system-ui,-apple-system,sans-serif}
h1{font-size:17px;margin:0 0 4px}
p.sub{margin:0 0 18px;color:var(--muted);font-size:13px}
canvas{width:100%;max-width:900px;height:auto;border:1px solid var(--grid);
border-radius:8px}
.row{display:flex;gap:18px;align-items:center;margin-top:14px;font-size:13px}
button{padding:7px 14px;font-size:13px;border-radius:6px;border:1px solid var(--grid);
background:transparent;color:var(--fg);cursor:pointer}
.stat{color:var(--muted);font-variant-numeric:tabular-nums}
</style>
<h1>Hypothesis swarm</h1>
<p class="sub">One dot per surviving hypothesis. Dots fade as probes refute them.
A red burst is a re-proposal: every hypothesis that factor held was wrong.</p>
<canvas id="c" width="900" height="420"></canvas>
<div class="row">
  <button id="replay">Replay</button>
  <span class="stat" id="stat"></span>
</div>
<script>
const DATA = __DATA__;
const cv = document.getElementById('c'), ctx = cv.getContext('2d');
const stat = document.getElementById('stat');
const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
const css = getComputedStyle(document.documentElement);

let dots = [];
function seed(n, burst){
  for (let i = 0; i < n; i++){
    dots.push({
      x: 40 + Math.random() * (cv.width - 80),
      y: 30 + Math.random() * (cv.height - 60),
      a: 1, burst: burst, born: performance.now()
    });
  }
}

function draw(){
  ctx.clearRect(0, 0, cv.width, cv.height);
  const dot = css.getPropertyValue('--dot').trim();
  const burst = css.getPropertyValue('--burst').trim();
  for (const d of dots){
    if (d.a <= 0) continue;
    ctx.globalAlpha = Math.max(0, d.a);
    ctx.fillStyle = d.burst ? burst : dot;
    ctx.beginPath();
    ctx.arc(d.x, d.y, d.burst ? 4 : 3, 0, Math.PI * 2);
    ctx.fill();
  }
  ctx.globalAlpha = 1;
}

function play(){
  dots = [];
  seed(DATA.initial, false);
  draw();
  let i = 0;
  if (reduce){
    stat.textContent = DATA.events.length + ' events \\u00b7 ' +
      DATA.reproposals + ' re-proposals';
    return;
  }
  const timer = setInterval(() => {
    if (i >= DATA.events.length){ clearInterval(timer); return; }
    const ev = DATA.events[i++];
    if (ev.kind === 'death'){
      let killed = 0;
      for (const d of dots){
        if (killed >= ev.n) break;
        if (d.a > 0 && !d.dying){ d.dying = true; killed++; }
      }
    } else {
      seed(ev.n, true);
    }
    for (const d of dots){ if (d.dying) d.a -= 0.34; }
    dots = dots.filter(d => d.a > 0.02);
    draw();
    stat.textContent = 'probe ' + ev.probe + ' \\u00b7 ' + dots.length +
      ' hypotheses alive';
  }, 110);
}

document.getElementById('replay').addEventListener('click', play);
play();
</script>
"""


def render(view: RunView, out: Path) -> Path | None:
    if not view.deaths and not view.reproposals:
        return None

    events = [
        {"kind": "death", "n": int(d.get("killed", 0)), "probe": i}
        for i, d in enumerate(view.deaths)
    ]
    for r in view.reproposals:
        events.append(
            {
                "kind": "reproposal",
                "n": int(r.get("new_particles", 0)),
                "probe": int(r.get("probes_used", 0)),
            }
        )
    events.sort(key=lambda e: e["probe"])

    data = {
        "initial": max(24, sum(int(d.get("surviving", 0)) for d in view.deaths[:1]) or 60),
        "events": events,
        "reproposals": len(view.reproposals),
        "agent": view.agent,
    }
    html = TEMPLATE.replace("__DATA__", json.dumps(data))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
