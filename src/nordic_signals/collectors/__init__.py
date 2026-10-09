"""One collector per source; each module's docstring documents its endpoints and terms."""

from .base import Collector, RunSummary
from .crypto import CryptoCollector
from .fi_insider import FiInsiderCollector
from .fi_short import FiShortCollector
from .mfn import MfnCollector
from .newsweb import NewsWebCollector
from .no_short import NoShortCollector
from .nordnet import NordnetCollector
from .pumpfun import PumpFunCollector
from .yahoo import PaperPricesCollector, SectorCollector, YahooCollector

COLLECTORS: dict[str, type[Collector]] = {
    c.source: c
    for c in (
        NewsWebCollector,
        FiInsiderCollector,
        FiShortCollector,
        NoShortCollector,
        MfnCollector,
        YahooCollector,
        PaperPricesCollector,
        SectorCollector,
        NordnetCollector,
        PumpFunCollector,
        CryptoCollector,
    )
}

__all__ = ["COLLECTORS", "Collector", "RunSummary"]
