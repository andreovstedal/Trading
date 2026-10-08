"""Check edge.py's pure-Python port against the bidask package (2.1.0) on cached Yahoo series.

Needs a Python with bidask and numpy (the project's venv has neither), for example:
    uv venv /tmp/bidask && VIRTUAL_ENV=/tmp/bidask uv pip install bidask numpy
    /tmp/bidask/bin/python research/b2_prices/check_edge.py --cache DIR
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from edge import edge  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    import bidask  # noqa: PLC0415

    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", type=Path, required=True)
    ap.add_argument("--windows", type=int, default=300)
    args = ap.parse_args(argv)
    files = sorted((args.cache / "yahoo").glob("*.json"))
    rng = random.Random(1)
    worst, n = 0.0, 0
    while n < args.windows:
        payload = json.loads(rng.choice(files).read_text())
        if "chart" not in payload or not payload["chart"].get("result"):
            continue
        q = payload["chart"]["result"][0]["indicators"]["quote"][0]
        o, h, lo, c = (q.get(k) or [] for k in ("open", "high", "low", "close"))
        if len(c) < 100:
            continue
        start = rng.randrange(0, len(c) - 63)
        cols = [[x if x and x > 0 else None for x in col[start:start + 63]] for col in (o, h, lo, c)]
        ours = edge(*cols)
        theirs = bidask.edge(*[[math.nan if x is None else x for x in col] for col in cols])
        if math.isnan(ours) and math.isnan(theirs):
            n += 1
            continue
        worst = max(worst, abs(ours - theirs))
        n += 1
    print(json.dumps({"windows": n, "max_abs_difference": worst}))


if __name__ == "__main__":
    main()
