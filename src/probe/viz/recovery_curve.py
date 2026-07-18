"""Contract F1 against probe budget, one line per agent.

The rigorous version of the claim, and the least interesting to look at. It
belongs below the animated figures, not above them.
"""

from __future__ import annotations

from pathlib import Path

from probe.viz.trace_export import RunView

W, H = 720, 420
PAD_L, PAD_B, PAD_T, PAD_R = 56, 48, 36, 24

COLOURS = {
    "random": "#9ca3af",
    "react": "#f59e0b",
    "hypothesis": "#10b981",
    "eig": "#2563eb",
}

CSS = """
.bg{fill:#ffffff}.fg{fill:#111111}.muted{fill:#6b7280}.axis{stroke:#d1d5db}
text{font-family:ui-sans-serif,system-ui,sans-serif}
@media (prefers-color-scheme:dark){
.bg{fill:#0b0f19}.fg{fill:#f3f4f6}.muted{fill:#9ca3af}.axis{stroke:#374151}}
"""


def render(views: list[RunView], out: Path, metric: str = "f1") -> Path | None:
    series = {
        v.agent: [(int(c["probes"]), float(c.get(metric, 0.0))) for c in v.checkpoints]
        for v in views
        if v.checkpoints
    }
    if not series:
        return None

    max_x = max(p for pts in series.values() for p, _ in pts) or 1
    plot_w, plot_h = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def sx(probes: int) -> float:
        return PAD_L + (probes / max_x) * plot_w

    def sy(value: float) -> float:
        return PAD_T + (1 - value) * plot_h

    parts = [
        f'<text x="{PAD_L}" y="24" class="fg" font-size="14" font-weight="600">'
        f"Contract {metric.upper()} vs probe budget</text>",
        f'<line x1="{PAD_L}" y1="{PAD_T}" x2="{PAD_L}" y2="{PAD_T + plot_h}" class="axis"/>',
        f'<line x1="{PAD_L}" y1="{PAD_T + plot_h}" x2="{PAD_L + plot_w}" '
        f'y2="{PAD_T + plot_h}" class="axis"/>',
    ]

    for tick in (0.0, 0.25, 0.5, 0.75, 1.0):
        y = sy(tick)
        parts.append(
            f'<line x1="{PAD_L - 4}" y1="{y}" x2="{PAD_L + plot_w}" y2="{y}" '
            f'class="axis" stroke-dasharray="2 4"/>'
        )
        parts.append(
            f'<text x="{PAD_L - 10}" y="{y + 4}" class="muted" font-size="11" '
            f'text-anchor="end">{tick:.2f}</text>'
        )
    for tick in range(0, max_x + 1, max(10, max_x // 5)):
        parts.append(
            f'<text x="{sx(tick)}" y="{PAD_T + plot_h + 18}" class="muted" '
            f'font-size="11" text-anchor="middle">{tick}</text>'
        )
    parts.append(
        f'<text x="{PAD_L + plot_w / 2}" y="{H - 8}" class="muted" font-size="11" '
        f'text-anchor="middle">probes sent</text>'
    )

    for i, (agent, points) in enumerate(sorted(series.items())):
        colour = COLOURS.get(agent, "#6b7280")
        path = " ".join(
            f"{'M' if j == 0 else 'L'}{sx(p):.1f},{sy(v):.1f}"
            for j, (p, v) in enumerate(sorted(points))
        )
        parts.append(f'<path d="{path}" fill="none" stroke="{colour}" stroke-width="2"/>')
        for p, v in points:
            parts.append(f'<circle cx="{sx(p):.1f}" cy="{sy(v):.1f}" r="3" fill="{colour}"/>')
        ly = PAD_T + 14 + i * 18
        parts.append(
            f'<rect x="{PAD_L + plot_w - 96}" y="{ly - 8}" width="10" height="10" '
            f'fill="{colour}"/>'
        )
        parts.append(
            f'<text x="{PAD_L + plot_w - 80}" y="{ly + 1}" class="fg" font-size="11">{agent}</text>'
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" '
        f'height="{H}"><style>{CSS}</style>'
        f'<rect width="{W}" height="{H}" class="bg"/>' + "\n".join(parts) + "</svg>"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    return out
