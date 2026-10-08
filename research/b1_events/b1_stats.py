"""Means with standard errors clustered by calendar month, optionally weighted and with Newey-West lags.

For values x_1..x_n with weights w_i (1 unless the row stands for several unsampled events), W = sum w_i, the
weighted mean m = sum w_i x_i / W, residuals e_i = x_i - m, and S_g = sum_{i in g} w_i e_i the residual sum of
calendar month g (the month of the entry day; G months with events):

    SE_cl^2 = G / (G - 1) * sum_g S_g^2 / W^2                                  t = m / SE_cl

(the CR1 sandwich for a weighted regression on a constant; Stata's small-sample factor reduces to G / (G - 1)).
Holding periods longer than a few days overlap across months, so for them the month sums are also treated as a
time series with Newey-West (Bartlett) weights over L lags, months without events counting as zero:

    SE_nw^2 = G / (G - 1) * [sum_g S_g^2 + 2 sum_{l=1..L} (1 - l / (L + 1)) sum_g S_g S_{g-l}] / W^2

which is SE_cl at L = 0. The plain t uses SE_iid = sd / sqrt(n) (unweighted rows only).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Hashable, Sequence


def _month_number(c: Hashable) -> int | None:
    """'YYYY-MM' -> a running month number, for the Newey-West lags."""
    if isinstance(c, str) and len(c) == 7 and c[4] == "-":
        return int(c[:4]) * 12 + int(c[5:]) - 1
    return None


def weighted_median(values: Sequence[float], weights: Sequence[float]) -> float:
    pairs = sorted(zip(values, weights, strict=True))
    half, run = sum(weights) / 2, 0.0
    for v, w in pairs:
        run += w
        if run >= half:
            return v
    return pairs[-1][0]


def summary(values: Sequence[float], clusters: Sequence[Hashable], weights: Sequence[float] | None = None,
            nw_lags: int | None = None) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0}
    w = list(weights) if weights is not None else [1.0] * n
    total = sum(w)
    m = sum(wi * v for wi, v in zip(w, values, strict=True)) / total
    weighted = any(abs(wi - 1.0) > 1e-12 for wi in w)
    out = {"n": n, "mean": m,
           "median": weighted_median(values, w) if weighted else statistics.median(values),
           "hit_rate": sum(wi for wi, v in zip(w, values, strict=True) if v > 0) / total}
    if weighted:
        out["weighted_n"] = total
    if n < 2:
        return out
    sums: dict[Hashable, float] = defaultdict(float)
    for v, c, wi in zip(values, clusters, w, strict=True):
        sums[c] += wi * (v - m)
    g = len(sums)
    out["clusters"] = g
    if not weighted:
        sd = statistics.stdev(values)
        se_iid = sd / math.sqrt(n)
        out.update(sd=sd, se_iid=se_iid, t_iid=m / se_iid if se_iid > 0 else None)
    if g >= 2:
        base = sum(s * s for s in sums.values())
        se_cl = math.sqrt(g / (g - 1) * base / (total * total))
        out.update(se_cl=se_cl, t_cl=m / se_cl if se_cl > 0 else None)
        if nw_lags:
            by_month = {_month_number(c): s for c, s in sums.items()}
            if None not in by_month:
                cross = sum((1 - lag / (nw_lags + 1)) * s * by_month.get(k - lag, 0.0)
                            for lag in range(1, nw_lags + 1) for k, s in by_month.items())
                var = g / (g - 1) * (base + 2 * cross) / (total * total)
                if var > 0:
                    se_nw = math.sqrt(var)
                    out.update(nw_lags=nw_lags, se_nw=se_nw, t_nw=m / se_nw)
    return out


def winsorize(values: Sequence[float], p: float = 0.01) -> list[float]:
    if len(values) < 3:
        return list(values)
    s = sorted(values)
    lo, hi = s[int(p * (len(s) - 1))], s[int(math.ceil((1 - p) * (len(s) - 1)))]
    return [min(max(v, lo), hi) for v in values]
