"""Small server-side SVG charts in the app's colour tokens.

* ``account_chart``: a fake-money account's value over time, in SOL by default (pump.fun) or in any currency
  (``money``), point by point or, for the stock account, day by day (``daily``). One series, so no legend
  (the card title names it); the starting amount is a dashed reference line, the line and the area to it are
  green above and pink below, and the latest value is labelled directly. The stock account's yardstick
  (``yardstick``) is a thin grey line, labelled at its end. A crosshair and tooltip follow the pointer
  (``static/charts.js``).
* ``sparkline``: one position's result after fees since it was bought, the same way around a dashed
  break-even line. A sold position's axis is its 24 hours; an open one's runs to now (at least an hour), so
  a new position's first minutes fill the chart.
* ``result_bars``: closed trades by result: gains, losses and the bins near zero in grey. Each bar has a
  tooltip; counts are in the table view under the chart.

Green and pink are a diverging pair that colour-blind readers can only just tell apart, so the reference
line, the bins' signed labels and the ▲/▼ beside each number say the same without colour. Text uses the
ink colours, never the series colours. Bars have 4 px rounded tops anchored to the baseline and a 2 px gap
between them.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable
from datetime import datetime
from typing import Any

from markupsafe import Markup, escape

from .. import text

WIDTH, HEIGHT = 640, 240
LEFT, RIGHT, TOP, BOTTOM = 52, 96, 14, 30  # at least; the account chart widens them for long labels
LABEL_WIDTH, VALUE_WIDTH = 7, 8  # about a character's width at the axis labels' and the value label's sizes
MIN_SPAN = 0.02  # the account chart always shows at least ±2 % around the start, so small moves look small
SPARK = {"card": (280, 84, 6), "mini": (120, 30, 3)}  # width, height, padding
SPARK_MIN_SPAN = 0.10  # a position's chart shows at least −10 % to +10 %


def account_chart(points: list[tuple[datetime, float]], start: float, *, live: bool = False,
                  money: Callable[[float], str] | None = None, daily: bool = False,
                  yardstick: list[tuple[datetime, float]] | None = None,
                  yardstick_label: str = "indeksene") -> Markup:
    """``live``: the last point is the value now, between two recorded ones. ``daily``: one point a day, labelled
    with the date only. ``yardstick``: what the account is measured against, at some or all of the same times."""
    if len(points) < 2:
        return Markup("")
    amount = money or _sol_amount
    stamp = _day if daily else _date_time
    t0, t1 = points[0][0].timestamp(), points[-1][0].timestamp()
    yardstick = [(t, v) for t, v in yardstick or [] if t0 <= t.timestamp() <= t1]
    values = [v for _, v in points] + [v for _, v in yardstick]
    lo, hi = _padded(min(*values, start * (1 - MIN_SPAN)), max(*values, start * (1 + MIN_SPAN)))
    span = max(t1 - t0, 1.0)
    ticks, digits = _ticks(lo, hi)
    # Room for the longest axis label and the latest value: kroner need more than SOL.
    left = max(LEFT, 14 + LABEL_WIDTH * max(len(text.number(v, digits)) for v in ticks))
    right = max(RIGHT, 16 + VALUE_WIDTH * len(amount(points[-1][1])))

    def x(ts: float) -> float:
        return round(left + (ts - t0) / span * (WIDTH - left - right), 1)

    def y(v: float) -> float:
        return round(TOP + (hi - v) / (hi - lo) * (HEIGHT - TOP - BOTTOM), 1)

    coords = [(x(t.timestamp()), y(v)) for t, v in points]
    parts = [_grid(ticks, digits, y, left, WIDTH - right),
             _split(coords, y(start), "acct", (left, TOP, WIDTH - right, HEIGHT - BOTTOM))]
    if len(yardstick) > 1:
        marks = [(x(t.timestamp()), y(v)) for t, v in yardstick]
        parts.append('<path class="yardstick" d="M' + " L".join(f"{cx},{cy}" for cx, cy in marks) + '"/>')
        end_x, end_y = marks[-1]
        clear = end_y + 16 if abs(end_y - coords[-1][1]) < 16 and end_y >= coords[-1][1] else end_y - 6 \
            if abs(end_y - coords[-1][1]) < 16 else end_y + 4
        parts.append(f'<text class="axis-label" x="{end_x + 8}" y="{clear}">{escape(yardstick_label)}</text>')
    # The start label goes on the side of the reference line that the first part of the line keeps away from.
    early = [v for _, v in points[:max(2, len(points) // 6)]]
    label_at = y(start) + 16 if sum(early) / len(early) >= start else y(start) - 6
    parts.append(f'<line class="ref" x1="{left}" x2="{WIDTH - right}" y1="{y(start)}" y2="{y(start)}"/>'
                 f'<text class="axis-label" x="{left + 6}" y="{label_at}">start {amount(start)}</text>')
    last_x, last_y = coords[-1]
    label_y = last_y - 10 if abs(last_y - y(start)) < 14 else last_y + 4
    side = "up" if points[-1][1] >= start else "down"
    parts.append(f'<circle class="dot {side}" cx="{last_x}" cy="{last_y}" r="4"/>'
                 f'<text class="value-label" x="{last_x + 8}" y="{label_y}">{amount(points[-1][1])}</text>')
    for when, cx in ((points[0][0], left), (points[-1][0], WIDTH - right)):
        anchor = "start" if cx == left else "end"
        label = "nå" if live and cx != left else stamp(when)
        parts.append(f'<text class="axis-label" x="{cx}" y="{HEIGHT - 8}" text-anchor="{anchor}">{label}</text>')
    parts.append(_hover(TOP, HEIGHT - BOTTOM, left, WIDTH - left - right))
    beside = {t: v for t, v in yardstick}
    data = [{"x": cx, "y": cy, "t": f"{stamp(when)} · {amount(v)}"
             + (f" · {yardstick_label} {amount(beside[when])}" if when in beside else "")}
            for (when, v), (cx, cy) in zip(points, coords, strict=True)]
    if live:
        data[-1]["t"] = f"nå · {amount(points[-1][1])}"
    label = (f"Kontoverdi fra {amount(points[0][1])} til {amount(points[-1][1])}, "
             f"{stamp(points[0][0])} til {'nå' if live else stamp(points[-1][0])}. Start: {amount(start)}.")
    if len(yardstick) > 1:
        label += f" {yardstick_label.capitalize()}: {amount(yardstick[-1][1])} {stamp(yardstick[-1][0])}."
    return _figure(parts, label, data, (WIDTH, HEIGHT))


def sparkline(series: list[tuple[datetime, float]], *, opened: datetime, until: datetime, key: str,
              size: str = "card", closed: bool = False, what: str = "Resultat etter gebyrer siden kjøpet",
              stamp: Callable[[datetime], str] | None = None) -> Markup:
    """``series``: (time, result after fees) from the purchase on, drawn from ``opened`` to ``until``.
    ``key`` makes the clip paths unique on the page; ``what`` names the line for screen readers, and ``stamp``
    writes the times in the tooltips (the time of day by default)."""
    if not series:
        return Markup("")
    width, height, pad = SPARK[size]
    values = [v for _, v in series]
    lo, hi = min(*values, -SPARK_MIN_SPAN), max(*values, SPARK_MIN_SPAN)
    lo, hi = lo - (hi - lo) * 0.08, hi + (hi - lo) * 0.08
    t0, span = opened.timestamp(), max((until - opened).total_seconds(), 60.0)

    def x(when: datetime) -> float:
        return round(pad + min(max((when.timestamp() - t0) / span, 0), 1) * (width - 2 * pad), 1)

    def y(v: float) -> float:
        return round(pad + (hi - v) / (hi - lo) * (height - 2 * pad), 1)

    coords = [(x(t), y(v)) for t, v in series]
    zero = y(0)
    side = "up" if values[-1] >= 0 else "down"
    parts = [f'<line class="ref" x1="{pad}" x2="{width - pad}" y1="{zero}" y2="{zero}"/>',
             _split(coords, zero, f"{size}-{key}", (0, 0, width, height))]
    parts.append(f'<circle class="dot {side}" cx="{coords[-1][0]}" cy="{coords[-1][1]}" r="{3 if size == "mini" else 4}"/>')
    data = None
    if size == "card":
        parts.append(_hover(pad, height - pad, pad, width - 2 * pad))
        data = [{"x": cx, "y": cy, "t": f"{(stamp or _clock)(when)} · {text.percent(v, 1, True)}"}
                for (when, v), (cx, cy) in zip(series, coords, strict=True)]
    how = "endte på" if closed else "nå"
    label = (f"{what}: {how} {text.percent(values[-1], 0, True)}, høyeste "
             f"{text.percent(max(values), 0, True)}, laveste {text.percent(min(values), 0, True)}.")
    return _figure(parts, label, data, (width, height), css=f"spark spark-{size}")


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
    return _figure(parts, label, None, (WIDTH, HEIGHT))


def _split(coords: list[tuple[float, float]], base: float, key: str, box: tuple[float, float, float, float]) -> str:
    """The line and the area between it and ``base``: green where it is above, pink where it is below."""
    left, top, right, bottom = box
    line = "M" + " L".join(f"{cx},{cy}" for cx, cy in coords)
    area = f"{line} L{coords[-1][0]},{base} L{coords[0][0]},{base} Z"
    clips = (f'<clipPath id="{key}-up"><rect x="{left}" y="{top}" width="{right - left}" '
             f'height="{max(base - top, 0)}"/></clipPath>'
             f'<clipPath id="{key}-down"><rect x="{left}" y="{base}" width="{right - left}" '
             f'height="{max(bottom - base, 0)}"/></clipPath>')
    return (f"<defs>{clips}</defs>"
            + "".join(f'<path class="area {side}" d="{area}" clip-path="url(#{key}-{side})"/>' for side in ("up", "down"))
            + "".join(f'<path class="line {side}" d="{line}" clip-path="url(#{key}-{side})"/>'
                      for side in ("up", "down")))


def _hover(top: float, bottom: float, left: float, width: float) -> str:
    return (f'<line class="cross" x1="0" x2="0" y1="{top}" y2="{bottom}" visibility="hidden"/>'
            f'<circle class="dot hover" r="4" visibility="hidden"/>'
            f'<rect class="hit" x="{left}" y="{top}" width="{width}" height="{bottom - top}"/>')


def _figure(parts: list[str], label: str, data: list[dict[str, Any]] | None, size: tuple[int, int], *,
            css: str = "") -> Markup:
    # Single quotes around the JSON, so its many double quotes need no escaping: a page has dozens of these.
    points = json.dumps(data, ensure_ascii=False, separators=(",", ":")) if data else ""
    attrs = (" data-points='" + points.replace("&", "&amp;").replace("'", "&#39;").replace("<", "&lt;") + "'"
             if data else "")
    svg = (f'<svg viewBox="0 0 {size[0]} {size[1]}" role="img" aria-label="{escape(label)}">'
           + "".join(parts) + "</svg>")
    tip = '<div class="tip" hidden></div>' if data else ""
    return Markup(f'<div class="chart{" " + css if css else ""}"{attrs}>{svg}{tip}</div>')


def _grid(ticks: list[float], digits: int, y: Any, left: float = LEFT, right: float = WIDTH - RIGHT) -> str:
    out = []
    for v in ticks:
        out.append(f'<line class="grid" x1="{left}" x2="{right}" y1="{y(v)}" y2="{y(v)}"/>'
                   f'<text class="axis-label" x="{left - 8}" y="{y(v) + 4}" text-anchor="end">'
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


def _sol_amount(value: float) -> str:
    return f"{text.number(value, 3)}{text.NBSP}SOL"


def _date_time(value: datetime) -> str:
    local = value.astimezone(text.OSLO)
    return f"{local.day}. {text.MONTHS[local.month - 1]} {local:%H:%M}"


def _day(value: datetime) -> str:
    local = value.astimezone(text.OSLO)
    return f"{local.day}. {text.MONTHS[local.month - 1]}"


def _clock(value: datetime) -> str:
    return f"{value.astimezone(text.OSLO):%H:%M}"
