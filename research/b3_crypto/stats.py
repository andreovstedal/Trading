"""Statistics for B3: the Sharpe ratio's moments and the deflated Sharpe ratio (Bailey and Lopez de Prado, 2014).

    SR       = mean(r) / sd(r), on daily returns, not annualised
    PSR(SR*) = Phi( (SR - SR*) sqrt(T - 1) / sqrt(1 - g3 SR + (g4 - 1) / 4 SR^2) )
    SR0      = sqrt(V) ((1 - gamma) Phi^-1(1 - 1/N) + gamma Phi^-1(1 - 1/(N e)))
    DSR      = PSR(SR0)

g3 is the skewness and g4 the (Pearson) kurtosis of the returns, T their number, N the number of trials, V the
variance of the trials' Sharpe ratios and gamma the Euler-Mascheroni constant.
"""

from __future__ import annotations

import math
from statistics import NormalDist, fmean, median, variance

EULER = 0.5772156649015329
NORMAL = NormalDist()


def moments(r: list[float]) -> dict[str, float]:
    t = len(r)
    mu = fmean(r)
    m2 = sum((x - mu) ** 2 for x in r) / t
    m3 = sum((x - mu) ** 3 for x in r) / t
    m4 = sum((x - mu) ** 4 for x in r) / t
    sd = math.sqrt(m2)
    return {"T": t, "mean": mu, "sd": sd, "sr": mu / sd, "skew": m3 / sd ** 3, "kurtosis": m4 / m2 ** 2}


def psr(m: dict[str, float], sr_star: float) -> float:
    sr = m["sr"]
    denom = 1 - m["skew"] * sr + (m["kurtosis"] - 1) / 4 * sr ** 2
    return NORMAL.cdf((sr - sr_star) * math.sqrt(m["T"] - 1) / math.sqrt(denom))


def expected_max_sr(srs: list[float]) -> float:
    """SR0: the highest Sharpe ratio N trials with no skill would be expected to show."""
    n = len(srs)
    return math.sqrt(variance(srs)) * ((1 - EULER) * NORMAL.inv_cdf(1 - 1 / n)
                                       + EULER * NORMAL.inv_cdf(1 - 1 / (n * math.e)))


def deflated(returns: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    """Each trial's Sharpe ratio, moments and deflated Sharpe ratio, the trials being all of ``returns``."""
    ms = {k: moments(r) for k, r in returns.items()}
    sr0 = expected_max_sr([m["sr"] for m in ms.values()])
    out = {}
    for k, m in ms.items():
        out[k] = m | {"sr_annual": m["sr"] * math.sqrt(365), "sr0": sr0, "sr0_annual": sr0 * math.sqrt(365),
                      "psr0": psr(m, 0.0), "dsr": psr(m, sr0)}
    return out


def difference(a: list[float], b: list[float]) -> dict[str, float]:
    """The yearly difference in log growth between two daily return series, with its standard error
    (365 mean(d), 365 sd(d) / sqrt(T), d = log(1 + a) - log(1 + b), days taken as independent)."""
    d = [math.log1p(x) - math.log1p(y) for x, y in zip(a, b, strict=True)]
    m = moments(d)
    return {"per_year": 365 * m["mean"], "se": 365 * m["sd"] / math.sqrt(m["T"]),
            "t": m["mean"] / (m["sd"] / math.sqrt(m["T"]))}


def quartiles(xs: list[float]) -> tuple[float, float, float]:
    s = sorted(xs)

    def q(p: float) -> float:
        i = p * (len(s) - 1)
        lo, hi = math.floor(i), math.ceil(i)
        return s[lo] + (s[hi] - s[lo]) * (i - lo)

    return q(0.25), median(s), q(0.75)
