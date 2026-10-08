"""B2: the score's price-only part (pre-registered in research/PREREGISTRATION.md).

Run:  .venv/bin/python research/b2_prices/b2.py [--cache DIR] [--offline] [--download-only]
      [--undo REPAIR --out DIR]  (one of backtest.REPAIRS turned off, to measure what it changed)
      [--no-attribution]  (skip the four leave-one-repair-out runs that "Changed after the check" reports)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from data import Downloader  # noqa: E402
from universe import COUNTRIES, nordnet_universe  # noqa: E402

DEFAULT_CACHE = Path("/tmp/claude-0/-home-user-Trading/0a31d734-cb89-583d-8276-7cd774b8c998/scratchpad/data/b2_prices")
INDEXES = {"NO": "OSEBX.OL", "SE": "^OMXSBGI"}
FX = "SEKNOK=X"

log = logging.getLogger("b2")


def download(dl: Downloader) -> tuple[list, dict]:
    instruments = []
    for country in COUNTRIES:
        ins, _ = dl.nordnet(country)
        instruments += ins
    stocks, dropped = nordnet_universe(instruments)
    log.info("Nordnet: %d instruments, %d shares kept, dropped %s", len(instruments), len(stocks), dropped)
    from backtest import DELISTED_EXAMPLES  # noqa: PLC0415

    for symbol in [*INDEXES.values(), FX, *DELISTED_EXAMPLES]:  # the last: taken over, to show the survivorship gap
        dl.yahoo_daily(symbol)
    for n, stock in enumerate(stocks, 1):
        dl.yahoo_daily(stock.yahoo)
        if n % 50 == 0:
            log.info("Yahoo: %d of %d (%d network requests)", n, len(stocks), dl.network_requests)
    return stocks, dropped


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="download cache directory")
    ap.add_argument("--offline", action="store_true", help="use only the cache; fail on anything missing")
    ap.add_argument("--download-only", action="store_true")
    ap.add_argument("--out", type=Path, default=HERE, help="where results.json and results.md go")
    ap.add_argument("--undo", action="append", default=[], help="turn off one of backtest.REPAIRS (repeatable)")
    ap.add_argument("--no-attribution", action="store_true", help="skip the leave-one-repair-out runs (faster)")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    dl = Downloader(args.cache, offline=args.offline)
    try:
        stocks, dropped = download(dl)
        if args.download_only:
            return
        from backtest import REPAIRS, run  # noqa: PLC0415

        for name in args.undo:
            if name not in REPAIRS:
                ap.error(f"--undo {name}: not one of {', '.join(REPAIRS)}")
            REPAIRS[name] = False
        args.out.mkdir(parents=True, exist_ok=True)
        run(dl, stocks, dropped, args.out, attribution=not (args.no_attribution or args.undo))
    finally:
        dl.close()


if __name__ == "__main__":
    main()
