"""The EDGE bid-ask spread estimator (Ardia, Guidotti and Kroencke, JFE 2024) from daily OHLC.

A pure-Python port of ``bidask.edge`` (the authors' reference package, version 2), since the project's venv has no
numpy. It returns the estimated full proportional spread (0.01 is 1 %); the half-spread is half of it.
``check_edge.py`` compares it with the package on cached series (they agree to 1e-16).

    o, h, l, c = log prices; m = (h + l) / 2; primes are the previous day's values
    r1 = m - o, r2 = o - m', r3 = m - c', r4 = c' - m', r5 = o - c'
    tau = 1 if h != l or l != c' (the day had a range, or moved from yesterday's close)
    po = E[tau (o != h)] + E[tau (o != l)],  pc = E[tau (c' != h')] + E[tau (c' != l')],  pt = E[tau]
    d_k = r_k - E[r_k] / pt * tau
    x1 = -4/po d1 r2 - 4/pc d3 r4,  x2 = -4/po d1 r5 - 4/pc d5 r4
    s^2 = (v2 E[x1] + v1 E[x2]) / (v1 + v2) with v_k = Var[x_k];  spread = sqrt(|s^2|)
"""

from __future__ import annotations

import math
from collections.abc import Sequence


def _mean(xs: list[float]) -> float:
    return sum(xs) / len(xs) if xs else math.nan


def edge(open_: Sequence[float | None], high: Sequence[float | None], low: Sequence[float | None],
         close: Sequence[float | None], sign: bool = False) -> float:
    n = len(close)
    if n < 3:
        return math.nan

    def lg(x: float | None) -> float:
        return math.log(x) if x is not None and x > 0 else math.nan

    o = [lg(x) for x in open_]
    h = [lg(x) for x in high]
    lo = [lg(x) for x in low]
    c = [lg(x) for x in close]
    m = [(a + b) / 2 for a, b in zip(h, lo, strict=True)]

    rows = []  # one per day from the second, as (r1..r5, tau, po1, po2, pc1, pc2) with NaN for missing
    for t in range(1, n):
        h1, l1, c1, m1 = h[t - 1], lo[t - 1], c[t - 1], m[t - 1]
        ot, ht, lt, mt = o[t], h[t], lo[t], m[t]
        r1, r2, r3, r4, r5 = mt - ot, ot - m1, mt - c1, c1 - m1, ot - c1
        if math.isnan(ht) or math.isnan(lt) or math.isnan(c1):
            tau = math.nan
        else:
            tau = float(ht != lt or lt != c1)
        po1 = math.nan if math.isnan(ot) or math.isnan(ht) else tau * (ot != ht)
        po2 = math.nan if math.isnan(ot) or math.isnan(lt) else tau * (ot != lt)
        pc1 = math.nan if math.isnan(c1) or math.isnan(h1) else tau * (c1 != h1)
        pc2 = math.nan if math.isnan(c1) or math.isnan(l1) else tau * (c1 != l1)
        rows.append((r1, r2, r3, r4, r5, tau, po1, po2, pc1, pc2))

    def nanmean(k: int) -> float:
        return _mean([r[k] for r in rows if not math.isnan(r[k])])

    taus = [r[5] for r in rows if not math.isnan(r[5])]
    pt = _mean(taus)
    po = nanmean(6) + nanmean(7)
    pc = nanmean(8) + nanmean(9)
    if sum(taus) < 2 or po == 0 or pc == 0 or math.isnan(po) or math.isnan(pc):
        return math.nan
    mr1, mr3, mr5 = nanmean(0), nanmean(2), nanmean(4)
    x1s, x2s = [], []
    for r1, r2, r3, r4, r5, tau, *_ in rows:
        d1 = r1 - mr1 / pt * tau
        d3 = r3 - mr3 / pt * tau
        d5 = r5 - mr5 / pt * tau
        x1 = -4.0 / po * d1 * r2 + -4.0 / pc * d3 * r4
        x2 = -4.0 / po * d1 * r5 + -4.0 / pc * d5 * r4
        if not math.isnan(x1):
            x1s.append(x1)
        if not math.isnan(x2):
            x2s.append(x2)
    if not x1s or not x2s:
        return math.nan
    e1, e2 = _mean(x1s), _mean(x2s)
    v1 = _mean([x * x for x in x1s]) - e1 * e1
    v2 = _mean([x * x for x in x2s]) - e2 * e2
    vt = v1 + v2
    s2 = (v2 * e1 + v1 * e2) / vt if vt > 0 else (e1 + e2) / 2
    s = math.sqrt(abs(s2))
    return s * (1 if s2 >= 0 else -1) if sign else s
