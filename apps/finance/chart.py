"""The forecast chart, drawn as inline SVG on the server. No chart library."""

from __future__ import annotations

from decimal import Decimal

from django.utils.html import escape
from django.utils.safestring import mark_safe

WIDTH, HEIGHT = 880, 300
LEFT, RIGHT, TOP, BOTTOM = 56, 12, 16, 44
CONTRACTED = "#2f5d8a"
WEIGHTED = "#8bb3d9"
PAST = "#64748b"
TARGET = "#b45309"
INK = "#334155"


def _nice_max(value: Decimal) -> Decimal:
    if value <= 0:
        return Decimal(1000)
    magnitude = Decimal(10) ** (len(str(int(value))) - 1)
    for step in (1, 2, 2.5, 5, 10):
        top = magnitude * Decimal(str(step))
        if top >= value:
            return top
    return value


def forecast_svg(rows) -> str:
    """Bars of contracted income with the weighted pipeline on top, a line for the target, and
    grey bars for what Xero says was invoiced in past months."""
    if not rows:
        return ""
    peak = max(
        [r.forecast for r in rows]
        + [r.target for r in rows if r.target is not None]
        + [r.invoiced for r in rows if r.invoiced is not None],
        default=Decimal(0),
    )
    top = _nice_max(Decimal(peak))
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM
    slot = plot_w / len(rows)
    bar = slot * 0.62
    floor = TOP + plot_h

    def y(value) -> float:
        return floor - float(Decimal(value) / top) * plot_h

    def rect(x, y0, w, h, fill, title, opacity=""):
        extra = f' opacity="{opacity}"' if opacity else ""
        return (
            f'<rect x="{x:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{max(h, 0):.1f}" '
            f'fill="{fill}"{extra}><title>{escape(title)}</title></rect>'
        )

    parts = []
    for i in range(5):
        value = top * i / 4
        parts.append(
            f'<line x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y(value):.1f}" y2="{y(value):.1f}" '
            f'stroke="#e2e8f0"/><text x="{LEFT - 6}" y="{y(value) + 4:.1f}" text-anchor="end" '
            f'font-size="11" fill="{INK}">£{value:,.0f}</text>'
        )
    for index, row in enumerate(rows):
        x = LEFT + slot * index + (slot - bar) / 2
        label = f"{row.month:%b %y}"
        if row.past:
            parts.append(
                rect(
                    x,
                    y(row.contracted),
                    bar,
                    floor - y(row.contracted),
                    PAST,
                    f"{label}: contracted £{row.contracted:,.2f}",
                    "0.55",
                )
            )
            if row.invoiced is not None:
                parts.append(
                    rect(
                        x - 3,
                        y(row.invoiced) - 1.5,
                        bar + 6,
                        3,
                        INK,
                        f"{label}: invoiced £{row.invoiced:,.2f}",
                    )
                )
        else:
            parts.append(
                rect(
                    x,
                    y(row.contracted),
                    bar,
                    floor - y(row.contracted),
                    CONTRACTED,
                    f"{label}: contracted £{row.contracted:,.2f}",
                )
            )
            parts.append(
                rect(
                    x,
                    y(row.forecast),
                    bar,
                    y(row.contracted) - y(row.forecast),
                    WEIGHTED,
                    f"{label}: weighted pipeline £{row.weighted:,.2f}",
                )
            )
        parts.append(
            f'<text x="{x + bar / 2:.1f}" y="{HEIGHT - BOTTOM + 16}" text-anchor="middle" '
            f'font-size="11" fill="{INK}">{escape(label)}</text>'
        )
    points = [
        (LEFT + slot * i + slot / 2, y(r.target))
        for i, r in enumerate(rows)
        if r.target is not None
    ]
    if len(points) > 1:
        path = " ".join(f"{px:.1f},{py:.1f}" for px, py in points)
        parts.append(
            f'<polyline points="{path}" fill="none" stroke="{TARGET}" stroke-width="2.5" '
            'stroke-dasharray="6 4"/>'
        )
    for px, py in points:
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.5" fill="{TARGET}"/>')
    legend = [
        (CONTRACTED, "Contracted"),
        (WEIGHTED, "Weighted pipeline"),
        (PAST, "Past: contracted"),
        (TARGET, "Target (dashed line)"),
        (INK, "Invoiced in Xero (past)"),
    ]
    for i, (colour, text) in enumerate(legend):
        lx = LEFT + i * 152
        parts.append(
            f'<rect x="{lx}" y="{HEIGHT - 14}" width="12" height="12" fill="{colour}"/>'
            f'<text x="{lx + 17}" y="{HEIGHT - 4}" font-size="11" fill="{INK}">'
            f"{escape(text)}</text>"
        )
    return mark_safe(  # noqa: S308 - every value above is a number or escaped text
        f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="fc-title fc-desc" '
        'class="h-auto w-full"><title id="fc-title">Income forecast</title>'
        '<desc id="fc-desc">Contracted and weighted pipeline income for each month against the '
        f"target. The same figures are in the table below.</desc>{''.join(parts)}</svg>"
    )
