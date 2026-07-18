"""Probe tape: every probe in a run, shaded by what it actually taught.

One tape per agent, stacked and the same length. The contrast carries the
efficiency argument without a single number: a tape that is mostly flat is an
agent spending its budget on probes it already knew the answer to.
"""

from __future__ import annotations

from pathlib import Path

from probe.viz.trace_export import RunView

CELL, GAP, ROW = 9, 2, 54
LABEL = 96

CSS = """
.bg{fill:#ffffff}.fg{fill:#111111}.muted{fill:#6b7280}
text{font-family:ui-sans-serif,system-ui,sans-serif}
@media (prefers-color-scheme:dark){
.bg{fill:#0b0f19}.fg{fill:#f3f4f6}.muted{fill:#9ca3af}}
"""


def _shade(value: float, peak: float) -> str:
    """Flat grey for nothing learned, saturating blue for a lot."""
    if peak <= 0 or value <= 0:
        return "#d1d5db"
    t = min(1.0, value / peak)
    r = int(209 + (37 - 209) * t)
    g = int(213 + (99 - 213) * t)
    b = int(219 + (235 - 219) * t)
    return f"#{r:02x}{g:02x}{b:02x}"


def render(views: list[RunView], out: Path) -> Path | None:
    if not views:
        return None

    length = max(len(v.probes) for v in views)
    peak = max(
        (max(v.eig_by_probe(), default=0.0) for v in views),
        default=0.0,
    )
    width = LABEL + length * (CELL + GAP) + 40
    height = 44 + len(views) * ROW

    parts = [
        '<text x="16" y="26" class="fg" font-size="14" font-weight="600">'
        "Probe tape &#8212; each cell is one probe, shaded by information gained</text>"
    ]

    for row, view in enumerate(views):
        y = 44 + row * ROW
        parts.append(
            f'<text x="16" y="{y + 14}" class="fg" font-size="12">{view.agent}</text>'
        )
        series = view.eig_by_probe()
        for i in range(length):
            value = series[i] if i < len(series) else 0.0
            colour = _shade(value, peak) if i < len(view.probes) else "none"
            if colour == "none":
                continue
            x = LABEL + i * (CELL + GAP)
            parts.append(
                f'<rect x="{x}" y="{y}" width="{CELL}" height="20" rx="2" fill="{colour}"/>'
            )
        wasted = sum(1 for v in series if v <= 0)
        parts.append(
            f'<text x="16" y="{y + 32}" class="muted" font-size="10">'
            f"{wasted}/{len(series)} flat</text>"
        )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}"><style>{CSS}</style>'
        f'<rect width="{width}" height="{height}" class="bg"/>' + "\n".join(parts) + "</svg>"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(svg, encoding="utf-8")
    return out
