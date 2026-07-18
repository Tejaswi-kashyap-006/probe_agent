"""The partition split: why the agent picks what it picks.

One probe, the hypothesis set fanning into outcome buckets. An even split is
highlighted; a unanimous one is greyed, because it is a wasted probe. Shown
side by side, the two make the selection rule legible without any maths.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from probe.viz.trace_export import RunView

W, H = 900, 380
PANEL = W // 2

CSS = """
.bg{fill:#ffffff}.fg{fill:#111111}.muted{fill:#6b7280}
.live{fill:#2563eb}.dead{fill:#9ca3af}.rule{stroke:#d1d5db;stroke-width:1}
text{font-family:ui-sans-serif,system-ui,sans-serif}
@media (prefers-color-scheme:dark){
.bg{fill:#0b0f19}.fg{fill:#f3f4f6}.muted{fill:#9ca3af}
.live{fill:#60a5fa}.dead{fill:#4b5563}.rule{stroke:#374151}}
"""


def _panel(step: dict[str, Any], x0: int, title: str, wasted: bool) -> str:
    buckets: dict[str, float] = step.get("partition") or {}
    total = sum(buckets.values()) or 1.0
    eig = float(step.get("eig", 0.0))
    cls = "dead" if wasted else "live"

    parts = [
        f'<text x="{x0 + 24}" y="40" class="fg" font-size="15" font-weight="600">{title}</text>',
        f'<text x="{x0 + 24}" y="62" class="muted" font-size="12">'
        f'EIG = {eig:.2f} bits &#183; {int(total)} hypotheses</text>',
        f'<text x="{x0 + 24}" y="86" class="muted" font-size="11">'
        f'{_escape(str(step.get("chosen", ""))[:56])}</text>',
    ]

    y = 118
    for outcome, weight in sorted(buckets.items(), key=lambda kv: -kv[1]):
        width = int((weight / total) * (PANEL - 140))
        parts.append(
            f'<rect x="{x0 + 90}" y="{y}" width="{max(width, 2)}" height="20" '
            f'rx="3" class="{cls}"/>'
        )
        parts.append(
            f'<text x="{x0 + 82}" y="{y + 15}" class="fg" font-size="12" '
            f'text-anchor="end">{_escape(outcome)}</text>'
        )
        parts.append(
            f'<text x="{x0 + 98 + max(width, 2)}" y="{y + 15}" class="muted" '
            f'font-size="11">{int(weight)}</text>'
        )
        y += 30

    note = (
        "every hypothesis agrees &#8212; teaches nothing"
        if wasted
        else "splits the survivors &#8212; one probe, real information"
    )
    parts.append(
        f'<text x="{x0 + 24}" y="{H - 28}" class="muted" font-size="12">{note}</text>'
    )
    return "\n".join(parts)


def _escape(text: str) -> str:
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def render(view: RunView, out: Path) -> Path | None:
    """One high-EIG and one zero-EIG probe from a real run, side by side."""
    steps = [s for s in view.eig_steps if s.get("partition")]
    if not steps:
        return None

    best = max(steps, key=lambda s: float(s.get("eig", 0.0)))
    zero = next((s for s in steps if float(s.get("eig", 0.0)) == 0.0), None)

    body = [_panel(best, 0, "High EIG: the probe it chose", wasted=False)]
    if zero is not None:
        body.append(f'<line x1="{PANEL}" y1="24" x2="{PANEL}" y2="{H - 50}" class="rule"/>')
        body.append(_panel(zero, PANEL, "Zero EIG: a wasted probe", wasted=True))

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}"><style>{CSS}</style>'
        f'<rect width="{W}" height="{H}" class="bg"/>' + "\n".join(body) + "</svg>"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    return out
