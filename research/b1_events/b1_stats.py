"""Means with standard errors clustered by calendar month.

For values x_1..x_n in G clusters (calendar months of the entry day), with mean m and residuals e_i = x_i - m:

    SE_cl^2 = G / (G - 1) * sum_g (sum_{i in g} e_i)^2 / n^2        t = m / SE_cl

(the CR1 sandwich for a regression on a constant; Stata's small-sample factor reduces to G / (G - 1)). The plain
t uses SE_iid = sd / sqrt(n).
"""

from __future__ import annotations

import math
import statistics
from collections import defaultdict
from collections.abc import Hashable, Sequence


def summary(values: Sequence[float], clusters: Sequence[Hashable]) -> dict:
    n = len(values)
    if n == 0:
        return {"n": 0}
    m = statistics.fmean(values)
    out = {"n": n, "mean": m, "median": statistics.median(values),
           "hit_rate": sum(1 for v in values if v > 0) / n}
    if n < 2:
        return out
    sd = statistics.stdev(values)
    sums: dict[Hashable, float] = defaultdict(float)
    for v, c in zip(values, clusters, strict=True):
        sums[c] += v - m
    g = len(sums)
    se_iid = sd / math.sqrt(n)
    out.update(sd=sd, se_iid=se_iid, t_iid=m / se_iid if se_iid > 0 else None, clusters=g)
    if g >= 2:
        se_cl = math.sqrt(g / (g - 1) * sum(s * s for s in sums.values()) / (n * n))
        out.update(se_cl=se_cl, t_cl=m / se_cl if se_cl > 0 else None)
    return out


def winsorize(values: Sequence[float], p: float = 0.01) -> list[float]:
    if len(values) < 3:
        return list(values)
    s = sorted(values)
    lo, hi = s[int(p * (len(s) - 1))], s[int(math.ceil((1 - p) * (len(s) - 1)))]
    return [min(max(v, lo), hi) for v in values]
