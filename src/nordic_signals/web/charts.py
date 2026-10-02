"""Small server-side SVG charts in the app's colour tokens, so they follow light and dark mode.

* ``account_chart``: the fake-money account's value over time. One series, so no legend (the card title
  names it); the starting amount is a dashed reference line; the latest value is labelled directly; a
  crosshair and tooltip follow the pointer (``static/charts.js``).
* ``result_bars``: closed trades by result. Blue for gains, orange for losses and grey near zero: a
  diverging pair colour-blind readers can tell apart, while the green and red status colours stay reserved
  for status. Each bar has a tooltip; counts are in the table view under the chart.

Text uses the ink colours, never the series colours. Bars have 4 px rounded tops anchored to the baseline
and a 2 px gap between them.
"""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any

from markupsafe import Markup, escape

from .. import text

WIDTH, HEIGHT = 640, 240
LEFT, RIGHT, TOP, BOTTOM = 52, 84, 14, 30
MIN_SPAN = 0.02  # the account chart always shows at least ±2 % around the start, so small moves look small


def account_chart(points: list[tuple[datetime, float]], start: float) -> Markup:
    if len(points) < 2:
        return Markup("")
    t0, t1 = points[0][0].timestamp(), points[-1][0].timestamp()
    values = [v for _, v in points]
    lo, hi = _padded(min(*values, start * (1 - MIN_SPAN)), max(*values, start * (1 + MIN_SPAN)))
    span = max(t1 - t0, 1.0)

    def x(ts: float) -> float:
        return round(LEFT + (ts - t0) / span * (WIDTH - LEFT - RIGHT), 1)

    def y(v: float) -> float:
        return round(TOP + (hi - v) / (hi - lo) * (HEIGHT - TOP - BOTTOM), 1)

    coords = [(x(t.timestamp()), y(v)) for t, v in points]
    ticks, digits = _ticks(lo, hi)
    parts = [_grid(ticks, digits, y)]
    parts.append(f'<line class="ref" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y(start)}" y2="{y(start)}"/>'
                 f'<text class="axis-label" x="{LEFT + 6}" y="{y(start) - 6}">start {_sol(start)}</text>')
    parts.append('<path class="line" d="M' + " L".join(f"{cx},{cy}" for cx, cy in coords) + '"/>')
    last_x, last_y = coords[-1]
    label_y = last_y - 10 if abs(last_y - y(start)) < 14 else last_y + 4
    parts.append(f'<circle class="dot" cx="{last_x}" cy="{last_y}" r="4"/>'
                 f'<text class="value-label" x="{last_x + 8}" y="{label_y}">{_sol(points[-1][1])}</text>')
    for when, cx in ((points[0][0], LEFT), (points[-1][0], WIDTH - RIGHT)):
        anchor = "start" if cx == LEFT else "end"
        parts.append(f'<text class="axis-label" x="{cx}" y="{HEIGHT - 8}" text-anchor="{anchor}">{_when(when)}</text>')
    parts.append(f'<line class="cross" x1="0" x2="0" y1="{TOP}" y2="{HEIGHT - BOTTOM}" visibility="hidden"/>'
                 f'<circle class="dot hover" r="4" visibility="hidden"/>'
                 f'<rect class="hit" x="{LEFT}" y="{TOP}" width="{WIDTH - LEFT - RIGHT}" '
                 f'height="{HEIGHT - TOP - BOTTOM}"/>')
    data = [{"x": cx, "y": cy, "t": f"{_when(when)} · {_sol(v)}"} for (when, v), (cx, cy) in zip(points, coords,
                                                                                                strict=True)]
    label = (f"Kontoverdi fra {_sol(points[0][1])} til {_sol(points[-1][1])}, "
             f"{_when(points[0][0])} til {_when(points[-1][0])}. Start: {_sol(start)}.")
    return _figure(parts, label, data)


def result_bars(bins: list[dict[str, Any]]) -> Markup:
    counts = [b["count"] for b in bins]
    if not sum(counts):
        return Markup("")
    ticks, _ = _ticks(0, max(counts), integer=True)
    top = max(ticks[-1], max(counts))

    def y(v: float) -> float:
        return round(TOP + (top - v) / top * (HEIGHT - TOP - BOTTOM), 1)

    parts = [_grid(ticks, 0, y)]
    slot = (WIDTH - LEFT - 16) / len(bins)
    base = y(0)
    for i, b in enumerate(bins):
        x0 = round(LEFT + i * slot + 1, 1)  # 2 px between neighbouring bars
        width = round(slot - 2, 1)
        css = {-1: "neg", 0: "mid", 1: "pos"}[b["polarity"]]
        if b["count"]:
            top_y = y(b["count"])
            r = min(4.0, (base - top_y) / 2, width / 2)
            path = (f"M{x0},{base} L{x0},{top_y + r} Q{x0},{top_y} {x0 + r},{top_y} "
                    f"L{x0 + width - r},{top_y} Q{x0 + width},{top_y} {x0 + width},{top_y + r} "
                    f"L{x0 + width},{base} Z")
            unit = "handel" if b["count"] == 1 else "handler"
            parts.append(f'<path class="bar {css}" d="{path}"><title>{escape(b["label"])} %: '
                         f'{b["count"]} {unit}</title></path>')
        parts.append(f'<text class="axis-label" x="{round(x0 + width / 2, 1)}" y="{HEIGHT - 8}" '
                     f'text-anchor="middle">{escape(b["label"])}</text>')
    label = "Lukkede handler etter resultat: " + ", ".join(f'{b["label"]} %: {b["count"]}' for b in bins) + "."
    return _figure(parts, label, None)


def _figure(parts: list[str], label: str, data: list[dict[str, Any]] | None) -> Markup:
    attrs = f' data-points="{escape(json.dumps(data))}"' if data else ""
    svg = (f'<svg viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="{escape(label)}">'
           + "".join(parts) + "</svg>")
    return Markup(f'<div class="chart"{attrs}>{svg}<div class="tip" hidden></div></div>')


def _grid(ticks: list[float], digits: int, y: Any) -> str:
    out = []
    for v in ticks:
        out.append(f'<line class="grid" x1="{LEFT}" x2="{WIDTH - RIGHT}" y1="{y(v)}" y2="{y(v)}"/>'
                   f'<text class="axis-label" x="{LEFT - 8}" y="{y(v) + 4}" text-anchor="end">'
                   f'{text.number(v, digits)}</text>')
    return "".join(out)


def _ticks(lo: float, hi: float, *, count: int = 4, integer: bool = False) -> tuple[list[float], int]:
    """Round tick values from ``lo`` to ``hi`` (1, 2, 2.5 or 5 times a power of ten) and the decimals they need."""
    raw = max((hi - lo) / count, 1e-9)
    power = 10 ** math.floor(math.log10(raw))
    step = next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)
    if integer:
        step = max(1, math.ceil(step))
    first = math.ceil(lo / step) * step
    ticks = []
    value = first
    while value <= hi + step * 1e-9:
        ticks.append(round(value, 10))
        value += step
    digits = max(0, -math.floor(math.log10(step))) if step < 1 else (1 if step % 1 else 0)
    return ticks, digits


def _padded(lo: float, hi: float) -> tuple[float, float]:
    pad = (hi - lo) * 0.1 or max(abs(hi) * 0.02, 0.01)
    return lo - pad, hi + pad


def _sol(value: float) -> str:
    return f"{text.number(value, 2)}{text.NBSP}SOL"


def _when(value: datetime) -> str:
    local = value.astimezone(text.OSLO)
    return f"{local.day}. {text.MONTHS[local.month - 1]} {local:%H:%M}"
